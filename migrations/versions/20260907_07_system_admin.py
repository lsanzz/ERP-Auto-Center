"""Create isolated system administration tables for MySQL."""
from alembic import op
import sqlalchemy as sa


revision = '20260907_07'
down_revision = '20260907_06'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'system_admins',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(80), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(120), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('last_login_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('username', name='uq_system_admins_username'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4',
    )
    op.create_table(
        'managed_companies',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('focus_company_id', sa.String(80), nullable=False),
        sa.Column('document', sa.String(20)),
        sa.Column('legal_name', sa.String(160)),
        sa.Column('trade_name', sa.String(160)),
        sa.Column('email', sa.String(120)),
        sa.Column('phone', sa.String(30)),
        sa.Column('city', sa.String(100)),
        sa.Column('state', sa.String(2)),
        sa.Column('remote_status', sa.String(40)),
        sa.Column('certificate_expires_at', sa.DateTime()),
        sa.Column('remote_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('last_synced_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('focus_company_id', name='uq_managed_companies_focus_id'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4',
    )
    op.create_index('ix_managed_companies_document', 'managed_companies', ['document'])


def downgrade():
    op.drop_table('managed_companies')
    op.drop_table('system_admins')
