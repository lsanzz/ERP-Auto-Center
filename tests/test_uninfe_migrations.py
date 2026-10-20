"""Exercise UniNFe upgrades against an existing database, not create_all."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT


def migrations():
    directory = Path(__file__).resolve().parents[1] / 'migrations' / 'versions'
    names = (
        '20260922_11_uninfe.py', '20260922_12_uninfe_submissions.py',
        '20260922_13_uninfe_dispatch.py', '20260923_14_uninfe_cancel.py',
        '20260923_15_uninfe_event_archive.py', '20260924_16_fiscal_artifact_storage.py',
        '20260924_17_uninfe_relay.py',
    )
    result = []
    for name in names:
        spec = importlib.util.spec_from_file_location(Path(name).stem, directory / name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result.append(module)
    return result


class UniNFeMigrationTests(unittest.TestCase):
    def test_relay_downgrade_protects_delivery_history(self):
        migration = next(item for item in migrations() if item.revision == '20260924_17')
        operations = Mock()
        operations.get_bind.return_value.scalar.return_value = 1
        with patch.object(migration, 'op', operations):
            with self.assertRaises(RuntimeError):
                migration.downgrade()
            operations.drop_table.assert_not_called()
            operations.get_bind.return_value.scalar.return_value = 0
            migration.downgrade()
            operations.drop_table.assert_called_once_with('uninfe_relay_tasks')

    def test_upgrade_chain_preserves_existing_company_and_invoice(self):
        engine = sa.create_engine('sqlite://')
        try:
            with engine.begin() as connection:
                metadata = sa.MetaData()
                company = sa.Table('system_settings', metadata,
                    sa.Column('id', sa.Integer, primary_key=True),
                    sa.Column('company_name', sa.Text))
                invoices = sa.Table('fiscal_documents', metadata,
                    sa.Column('id', sa.Integer, primary_key=True),
                    sa.Column('request_payload', sa.Text),
                    sa.Column('response_payload', sa.Text), sa.Column('xml_content', sa.Text))
                metadata.create_all(connection)
                connection.execute(company.insert(), {'id': 1, 'company_name': 'Oficina existente'})
                connection.execute(invoices.insert(), {'id': 7, 'xml_content': '<historico/>'})
                operations = Operations(MigrationContext.configure(connection))
                previous = '20260914_10'
                for migration in migrations():
                    self.assertEqual(migration.down_revision, previous)
                    with patch.object(migration, 'op', operations):
                        migration.upgrade()
                    previous = migration.revision
                inspector = sa.inspect(connection)
                self.assertIn('uninfe_settings_json', {
                    column['name'] for column in inspector.get_columns('system_settings')})
                from app.models import UniNFeSubmission
                self.assertEqual(
                    {column['name'] for column in inspector.get_columns('uninfe_submissions')},
                    set(UniNFeSubmission.__table__.columns.keys()))
                constraints = inspector.get_unique_constraints('uninfe_submissions')
                self.assertTrue(any(item['name'] == 'uq_uninfe_fiscal_number' for item in constraints))
                self.assertEqual(connection.scalar(sa.select(company.c.company_name)), 'Oficina existente')
                self.assertEqual(connection.scalar(sa.select(invoices.c.xml_content)), '<historico/>')
        finally:
            engine.dispose()

    def test_mysql_widening_preserves_nullability_and_never_shrinks_on_downgrade(self):
        migration = next(item for item in migrations() if item.revision == '20260924_16')
        connection = Mock()
        connection.dialect.name = 'mysql'
        operations = Mock()
        operations.get_bind.return_value = connection
        inspector = Mock()
        inspector.get_columns.side_effect = lambda table: [
            {'name': name, 'type': sa.Text(),
             'nullable': name not in {'snapshot_json', 'prepared_xml'}}
            for name in migration.ARTIFACTS[table]]
        with patch.object(migration, 'op', operations), patch.object(migration.sa, 'inspect', return_value=inspector):
            migration.upgrade()
            self.assertEqual(operations.alter_column.call_count, 8)
            for call in operations.alter_column.call_args_list:
                self.assertIsInstance(call.kwargs['type_'], LONGTEXT)
                self.assertEqual(call.kwargs['existing_nullable'],
                                 call.args[1] not in {'snapshot_json', 'prepared_xml'})
            operations.reset_mock()
            migration.downgrade()
            operations.alter_column.assert_not_called()
