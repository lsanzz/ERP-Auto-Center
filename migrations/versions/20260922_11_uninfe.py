"""Persist company-owned UniNFe configuration."""
from alembic import op
import sqlalchemy as sa

revision = '20260922_11'
down_revision = '20260914_10'
branch_labels = None
depends_on = None


def upgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('system_settings')}
    if 'uninfe_settings_json' not in columns:
        op.add_column('system_settings', sa.Column('uninfe_settings_json', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('system_settings', 'uninfe_settings_json')
