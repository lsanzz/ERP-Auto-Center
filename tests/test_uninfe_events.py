from pathlib import Path
import unittest
from tempfile import TemporaryDirectory

from tests import test_uninfe_dispatch
from tests.test_uninfe_transport import response
from app.models import UniNFeSubmission, db
from app.uninfe_dispatch import issue
from app.uninfe_events import cancel, collect_cancellation, cancellation_prefix


class UniNFeEventsTests(unittest.TestCase):
    setUp = test_uninfe_dispatch.UniNFeDispatchTests.setUp
    tearDown = test_uninfe_dispatch.UniNFeDispatchTests.tearDown
    new_document = test_uninfe_dispatch.UniNFeDispatchTests.new_document
    setup_invoice = test_uninfe_dispatch.UniNFeDispatchTests.setup_invoice

    def authorized_document(self, directory):
        doc = self.setup_invoice(directory)
        issue(doc.id)
        doc.status = 'AUTORIZADO'
        doc.xml_content = response(key=doc.access_key).decode()
        db.session.commit()
        return doc

    def test_cancel_waits_for_matching_registered_event(self):
        with TemporaryDirectory() as directory:
            doc = self.authorized_document(directory)
            original = doc.xml_content
            cancel(doc.id, 'Cliente desistiu da compra antes da entrega')
            self.assertEqual(doc.status, 'CANCELAMENTO_PENDENTE')
            prefix = cancellation_prefix(doc.access_key)
            request = Path(directory) / (prefix + '-ped-eve.xml')
            self.assertTrue(request.exists())
            self.assertIn('<nProt>123456789012345</nProt>', request.read_text(encoding='utf-8'))
            request.unlink()
            cancel(doc.id, 'Cliente desistiu da compra antes da entrega')
            self.assertFalse(request.exists())
            result = (f'<retEvento xmlns="http://www.portalfiscal.inf.br/nfe"><infEvento>'
                f'<tpAmb>2</tpAmb><chNFe>{doc.access_key}</chNFe><tpEvento>110111</tpEvento>'
                '<nSeqEvento>1</nSeqEvento><cStat>135</cStat><nProt>123456789012345</nProt>'
                '</infEvento></retEvento>')
            (Path(directory) / (prefix + '-eve.xml')).write_text(result, encoding='utf-8')
            self.assertTrue(collect_cancellation(doc, UniNFeSubmission.query.one()))
            self.assertEqual(doc.status, 'CANCELADO')
            self.assertEqual(doc.xml_content, original)

    def test_short_justification_never_creates_event(self):
        with TemporaryDirectory() as directory:
            doc = self.authorized_document(directory)
            with self.assertRaises(ValueError):
                cancel(doc.id, 'erro')
            self.assertIsNone(UniNFeSubmission.query.one().cancellation_xml)
            self.assertEqual(doc.status, 'AUTORIZADO')

    def test_unlinked_event_does_not_cancel_invoice(self):
        with TemporaryDirectory() as directory:
            doc = self.authorized_document(directory)
            cancel(doc.id, 'Cliente desistiu da compra antes da entrega')
            result = (f'<retEvento xmlns="http://www.portalfiscal.inf.br/nfe"><infEvento>'
                f'<tpAmb>2</tpAmb><chNFe>{doc.access_key}</chNFe><tpEvento>110111</tpEvento>'
                '<nSeqEvento>1</nSeqEvento><cStat>136</cStat><xMotivo>Sem vínculo</xMotivo>'
                '</infEvento></retEvento>')
            (Path(directory) / (cancellation_prefix(doc.access_key) + '-eve.xml')).write_text(result, encoding='utf-8')
            collect_cancellation(doc, UniNFeSubmission.query.one())
            self.assertEqual(doc.status, 'CANCELAMENTO_PENDENTE')
            self.assertIn('136', doc.error_message)

    def test_processed_event_is_archived_without_replacing_invoice(self):
        with TemporaryDirectory() as directory:
            doc = self.authorized_document(directory)
            original = doc.xml_content
            cancel(doc.id, 'Cliente desistiu da compra antes da entrega')
            submission = UniNFeSubmission.query.one()
            prefix = cancellation_prefix(doc.access_key)
            from defusedxml import ElementTree as ET
            event = ET.fromstring(submission.cancellation_xml)[1]
            processed = (f'<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe">'
                + ET.tostring(event, encoding='unicode')
                + f'<retEvento><infEvento><tpAmb>2</tpAmb><chNFe>{doc.access_key}</chNFe>'
                '<tpEvento>110111</tpEvento><nSeqEvento>1</nSeqEvento><cStat>135</cStat>'
                '<nProt>123456789012345</nProt></infEvento></retEvento></procEventoNFe>')
            (Path(directory) / (prefix + '-procEventoNFe.xml')).write_text(processed, encoding='utf-8')
            collect_cancellation(doc, submission)
            self.assertEqual(doc.status, 'CANCELADO')
            self.assertEqual(doc.xml_content, original)
            self.assertEqual(submission.cancellation_processed_xml, processed)
