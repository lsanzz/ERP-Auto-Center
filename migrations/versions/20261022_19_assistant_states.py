"""Estado do assistente de IA (conversa e propostas) no servidor, fora do cookie de sessão."""
from alembic import op
import sqlalchemy as sa

revision = '20261022_19'
down_revision = '20261021_18'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'assistant_states',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('history_json', sa.Text(), nullable=False),
        sa.Column('drafts_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('assistant_states')
