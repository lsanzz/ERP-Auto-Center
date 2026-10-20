"""Preserve fiscal artifacts exceeding MySQL TEXT capacity."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT

revision = '20260924_16'
down_revision = '20260923_15'
branch_labels = None
depends_on = None

ARTIFACTS = {
    'fiscal_documents': ('request_payload', 'response_payload', 'xml_content'),
    'uninfe_submissions': ('snapshot_json', 'prepared_xml', 'cancellation_xml',
                          'cancellation_response', 'cancellation_processed_xml'),
}


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name not in {'mysql', 'mariadb'}:
        return  # Other supported dialects do not have MySQL TEXT's size limit.
    inspector = sa.inspect(connection)
    for table, names in ARTIFACTS.items():
        columns = {column['name']: column for column in inspector.get_columns(table)}
        for name in names:
            column = columns[name]
            op.alter_column(table, name, existing_type=column['type'],
                            existing_nullable=column['nullable'], type_=LONGTEXT())


def downgrade():
    # Intentionally retain the widened columns. Shrinking them risks truncating
    # authorized invoices and their audit trail. Older code works with LONGTEXT.
    pass
