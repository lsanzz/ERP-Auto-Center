"""Campos de atendimento da O.S.: desconto geral, tipo, problema, laudo e observações ao cliente."""
from alembic import op
import sqlalchemy as sa

revision = '20261021_18'
down_revision = '20260924_17'
branch_labels = None
depends_on = None

COLUMNS = (
    sa.Column('desconto', sa.Numeric(12, 2), nullable=False, server_default='0'),
    sa.Column('tipo_atendimento', sa.String(20)),
    sa.Column('problema_relatado', sa.Text()),
    sa.Column('laudo', sa.Text()),
    sa.Column('observacoes_cliente', sa.Text()),
)


def upgrade():
    existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('work_orders')}
    with op.batch_alter_table('work_orders') as batch:
        for column in COLUMNS:
            if column.name not in existing:  # bancos com AUTO_CREATE_SCHEMA já podem ter as colunas
                batch.add_column(column.copy())


def downgrade():
    with op.batch_alter_table('work_orders') as batch:
        for column in reversed(COLUMNS):
            batch.drop_column(column.name)
