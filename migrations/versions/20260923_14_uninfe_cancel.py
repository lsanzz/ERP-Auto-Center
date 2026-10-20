"""Preserve cancellation request and response independently from authorization."""
from alembic import op
import sqlalchemy as sa

revision = '20260923_14'
down_revision = '20260922_13'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('uninfe_submissions', sa.Column('cancellation_xml', sa.Text()))
    op.add_column('uninfe_submissions', sa.Column('cancellation_response', sa.Text()))


def downgrade():
    op.drop_column('uninfe_submissions', 'cancellation_response')
    op.drop_column('uninfe_submissions', 'cancellation_xml')
