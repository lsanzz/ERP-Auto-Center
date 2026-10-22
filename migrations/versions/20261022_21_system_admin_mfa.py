"""Verificação em duas etapas obrigatória para o painel do dono do sistema."""
from alembic import op
import sqlalchemy as sa

revision = '20261022_21'
down_revision = '20261022_20'
branch_labels = None
depends_on = None


def upgrade():
    existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('system_admins')}
    if 'mfa_secret_encrypted' not in existing:  # bancos com AUTO_CREATE_SCHEMA já podem ter a coluna
        with op.batch_alter_table('system_admins') as batch:
            batch.add_column(sa.Column('mfa_secret_encrypted', sa.Text()))


def downgrade():
    with op.batch_alter_table('system_admins') as batch:
        batch.drop_column('mfa_secret_encrypted')
