"""Remember ambiguous monitor publication attempts."""
from alembic import op
import sqlalchemy as sa

revision = '20260922_13'
down_revision = '20260922_12'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('uninfe_submissions', sa.Column('publication_started_at', sa.DateTime()))


def downgrade():
    op.drop_column('uninfe_submissions', 'publication_started_at')
