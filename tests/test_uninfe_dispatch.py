import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests import test_uninfe_preparation, test_uninfe_xml
from app.models import UniNFeSubmission, db
from app.uninfe_dispatch import issue, consult


class UniNFeDispatchTests(unittest.TestCase):
    setUp = test_uninfe_preparation.UniNFePreparationTests.setUp
    tearDown = test_uninfe_preparation.UniNFePreparationTests.tearDown
    new_document = test_uninfe_preparation.UniNFePreparationTests.new_document

    def setup_invoice(self, directory):
        fixture = test_uninfe_xml.UniNFeXmlTests()
        fixture.setUp()
        for key, value in fixture.company.items():
            setattr(self.settings, key, value)
        config = json.loads(self.settings.uninfe_settings_json) | fixture.config
        config.update(send_directory=directory, return_directory=directory, authorized_directory=directory)
        self.settings.uninfe_settings_json = json.dumps(config)
        db.session.commit()
        doc = self.new_document()
        doc.request_payload = json.dumps(fixture.payload)
        db.session.commit()
        return doc

    def test_complete_local_flow_without_external_service(self):
        with TemporaryDirectory() as directory:
            doc = self.setup_invoice(directory)
            issue(doc.id)
            key = doc.access_key
            target = Path(directory) / (key + '-nfe.xml')
            self.assertTrue(target.exists())
            submission = UniNFeSubmission.query.one()
            self.assertIsNotNone(submission.published_at)
            prepared = submission.prepared_xml
            # Simulate the monitor consuming the document. A retry must not
            # publish a second copy even though the original path is now absent.
            target.unlink()
            issue(doc.id)
            self.assertFalse(target.exists())
            self.assertEqual(UniNFeSubmission.query.count(), 1)
            processed = (f'<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">'
                + prepared.split('?>', 1)[1] + '<protNFe><infProt><tpAmb>2</tpAmb>'
                + f'<chNFe>{key}</chNFe><nProt>123456789012345</nProt>'
                + '<cStat>100</cStat><xMotivo>Autorizado</xMotivo></infProt></protNFe></nfeProc>')
            (Path(directory) / (key + '-procNFe.xml')).write_text(processed, encoding='utf-8')
            consult(doc)
            self.assertEqual(doc.status, 'AUTORIZADO')
            self.assertEqual(doc.xml_content, processed)

    def test_ambiguous_failure_never_republishes(self):
        with TemporaryDirectory() as directory:
            doc = self.setup_invoice(directory)
            with patch('app.uninfe_dispatch.publish_invoice', side_effect=OSError('interrupted')) as publish:
                with self.assertRaises(OSError):
                    issue(doc.id)
                issue(doc.id)
                self.assertEqual(publish.call_count, 1)
            self.assertEqual(doc.status, 'PROCESSANDO')
            self.assertIsNotNone(UniNFeSubmission.query.one().publication_started_at)

    def test_production_is_not_enabled_by_homologation_implementation(self):
        with TemporaryDirectory() as directory:
            doc = self.setup_invoice(directory)
            doc.environment = 'PRODUCAO'
            db.session.commit()
            with self.assertRaises(ValueError):
                issue(doc.id)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_nfce_uses_independent_number_and_publishes_model_65(self):
        with TemporaryDirectory() as directory:
            doc = self.setup_invoice(directory)
            config = json.loads(self.settings.uninfe_settings_json)
            config.update(document_models='55,65', nfce_series=2, nfce_next_number=7)
            self.settings.uninfe_settings_json = json.dumps(config)
            doc.document_type = 'NFCE'
            payload = json.loads(doc.request_payload)
            payload['invoice']['tipo_atendimento'] = '1'
            doc.request_payload = json.dumps(payload)
            db.session.commit()
            issue(doc.id)
            self.assertEqual(doc.access_key[20:22], '65')
            self.assertEqual(doc.numero, '7')
            self.assertEqual(doc.serie, '2')
            xml = (Path(directory) / (doc.access_key + '-nfe.xml')).read_text(encoding='utf-8')
            self.assertIn('<mod>65</mod>', xml)
            config = json.loads(self.settings.uninfe_settings_json)
            self.assertEqual(config['nfe_next_number'], 1)
            self.assertEqual(config['nfce_next_number'], 8)
