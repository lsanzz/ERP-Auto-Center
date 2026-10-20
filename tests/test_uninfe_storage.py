import unittest
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.schema import CreateTable

from app.models import FiscalDocument, UniNFeSubmission, db
from tests import test_uninfe_preparation
from app.uninfe_preparation import prepare


class UniNFeStorageTests(unittest.TestCase):
    setUp = test_uninfe_preparation.UniNFePreparationTests.setUp
    tearDown = test_uninfe_preparation.UniNFePreparationTests.tearDown
    new_document = test_uninfe_preparation.UniNFePreparationTests.new_document

    def test_mysql_ddl_uses_longtext_for_all_fiscal_artifacts(self):
        for model, names in (
            (FiscalDocument, ('request_payload', 'response_payload', 'xml_content')),
            (UniNFeSubmission, ('snapshot_json', 'prepared_xml', 'cancellation_xml',
                               'cancellation_response', 'cancellation_processed_xml')),
        ):
            ddl = str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
            for name in names:
                self.assertIn(name + ' LONGTEXT', ddl)
                self.assertEqual(model.__table__.c[name].type.compile(dialect=sqlite.dialect()), 'TEXT')

    def test_large_prepared_artifact_roundtrip_is_not_truncated(self):
        document = self.new_document()
        xml = '<prepared>' + ('Peça de reposição ' * 10000) + '</prepared>'
        self.assertGreater(len(xml.encode('utf-8')), 65535)
        submission = prepare(document.id, lambda *args: xml)
        db.session.commit()
        submission_id, document_id = submission.id, document.id
        db.session.remove()
        self.assertEqual(db.session.get(UniNFeSubmission, submission_id).prepared_xml, xml)
        self.assertEqual(db.session.get(FiscalDocument, document_id).xml_content, xml)
