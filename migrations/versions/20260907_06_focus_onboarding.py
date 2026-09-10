"""Company onboarding status (MySQL)."""
from alembic import op
import sqlalchemy as sa

revision = '20260907_06'
down_revision = '20260907_05'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('system_settings', sa.Column('focus_sync_status', sa.String(20)))
    op.add_column('system_settings', sa.Column('focus_synced_at', sa.DateTime()))


def downgrade():
    op.drop_column('system_settings', 'focus_synced_at')
    op.drop_column('system_settings', 'focus_sync_status')
