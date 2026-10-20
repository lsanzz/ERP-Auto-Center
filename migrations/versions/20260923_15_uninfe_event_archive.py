"""Archive the processed cancellation event alongside the authorized invoice."""
from alembic import op
import sqlalchemy as sa

revision = '20260923_15'
down_revision = '20260923_14'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('uninfe_submissions')}
    if 'cancellation_processed_xml' not in columns:
        op.add_column('uninfe_submissions', sa.Column('cancellation_processed_xml', sa.Text()))


def downgrade():
    op.drop_column('uninfe_submissions', 'cancellation_processed_xml')
