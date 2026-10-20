"""Durable delivery permissions for the outbound Windows connector."""
from alembic import op
import sqlalchemy as sa

revision = '20260924_17'
down_revision = '20260924_16'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('uninfe_relay_tasks',
        sa.Column('submission_id', sa.Integer(), sa.ForeignKey('uninfe_submissions.id'), primary_key=True),
        sa.Column('connector_id', sa.String(80), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')


def downgrade():
    # Delivery permissions are an audit trail: dropping them could allow replay.
    tasks = sa.table('uninfe_relay_tasks', sa.column('submission_id'))
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(tasks)):
        raise RuntimeError('Não remova a fila UniNFe enquanto houver histórico de entregas.')
    op.drop_table('uninfe_relay_tasks')
