"""Assinatura da instalação: plano, data paga e suspensão manual."""
from alembic import op
import sqlalchemy as sa

revision = '20261022_20'
down_revision = '20261022_19'
branch_labels = None
depends_on = None

COLUMNS = (
    sa.Column('subscription_plan', sa.String(40)),
    sa.Column('subscription_paid_until', sa.Date()),
    sa.Column('subscription_suspended', sa.Boolean(), nullable=False, server_default='0'),
)


def upgrade():
    existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('system_settings')}
    with op.batch_alter_table('system_settings') as batch:
        for column in COLUMNS:
            if column.name not in existing:  # bancos com AUTO_CREATE_SCHEMA já podem ter as colunas
                batch.add_column(column.copy())


def downgrade():
    with op.batch_alter_table('system_settings') as batch:
        for column in reversed(COLUMNS):
            batch.drop_column(column.name)
