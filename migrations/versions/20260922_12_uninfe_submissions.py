"""Durable fiscal identities and prepared invoices."""
from alembic import op
import sqlalchemy as sa

revision = '20260922_12'
down_revision = '20260922_11'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('uninfe_submissions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('fiscal_documents.id'), nullable=False),
        sa.Column('issuer_document', sa.String(14), nullable=False),
        sa.Column('environment', sa.String(20), nullable=False),
        sa.Column('model', sa.String(2), nullable=False),
        sa.Column('series', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('access_key', sa.String(44), nullable=False),
        sa.Column('issued_at', sa.String(32), nullable=False),
        sa.Column('snapshot_json', sa.Text(), nullable=False),
        sa.Column('prepared_xml', sa.Text(), nullable=False),
        sa.Column('xml_sha256', sa.String(64), nullable=False),
        sa.Column('published_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('document_id'), sa.UniqueConstraint('access_key'),
        sa.UniqueConstraint('issuer_document', 'environment', 'model', 'series', 'number',
                            name='uq_uninfe_fiscal_number'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')


def downgrade():
    op.drop_table('uninfe_submissions')
