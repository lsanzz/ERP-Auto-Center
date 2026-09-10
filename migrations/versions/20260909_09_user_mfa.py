"""Add optional TOTP MFA to application users."""
from alembic import op
import sqlalchemy as sa

revision = '20260909_09'
down_revision = '20260909_08'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('mfa_enabled', sa.Boolean(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('mfa_secret_encrypted', sa.Text()))


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_column('mfa_secret_encrypted')
        batch.drop_column('mfa_enabled')
