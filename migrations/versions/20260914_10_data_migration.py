"""Staging, progress and durable duplicate protection for data migrations."""
from alembic import op
import sqlalchemy as sa

revision = '20260914_10'
down_revision = '20260909_09'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('data_migrations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('storage_name', sa.String(80), nullable=False),
        sa.Column('entity', sa.String(30), nullable=False),
        sa.Column('source', sa.String(80), nullable=False),
        sa.Column('options_json', sa.Text(), nullable=False),
        sa.Column('headers_json', sa.Text(), nullable=False),
        sa.Column('mapping_json', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        *[sa.Column(name, sa.Integer(), nullable=False) for name in ('total', 'processed', 'imported', 'skipped', 'errors')],
        sa.Column('last_error', sa.String(500)),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_index('ix_data_migrations_status', 'data_migrations', ['status'])
    op.create_table('migration_rows',
        sa.Column('migration_id', sa.Integer(), sa.ForeignKey('data_migrations.id'), primary_key=True),
        sa.Column('number', sa.Integer(), primary_key=True),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('result', sa.String(20), nullable=False),
        sa.Column('message', sa.String(500)), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_table('migration_keys',
        sa.Column('digest', sa.String(64), primary_key=True),
        sa.Column('migration_id', sa.Integer(), sa.ForeignKey('data_migrations.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), mysql_engine='InnoDB', mysql_charset='utf8mb4')


def downgrade():
    op.drop_table('migration_keys')
    op.drop_table('migration_rows')
    op.drop_table('data_migrations')
