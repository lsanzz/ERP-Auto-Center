"""Remove the after-sales reminder feature."""
from alembic import op
import sqlalchemy as sa


revision = '20260906_04'
down_revision = '20260906_03'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('service_reminders')


def downgrade():
    op.create_table(
        'service_reminders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('vehicle_id', sa.Integer()),
        sa.Column('work_order_id', sa.Integer()),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('reminder_type', sa.String(40), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('notes', sa.String(255)),
        sa.Column('contacted_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name='fk_reminder_client'),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], name='fk_reminder_vehicle'),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], name='fk_reminder_order'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4',
    )
    op.create_index('ix_service_reminders_client_id', 'service_reminders', ['client_id'])
    op.create_index('ix_service_reminders_vehicle_id', 'service_reminders', ['vehicle_id'])
    op.create_index('ix_service_reminders_work_order_id', 'service_reminders', ['work_order_id'])
    op.create_index('ix_service_reminders_due_date', 'service_reminders', ['due_date'])
    op.create_index('ix_service_reminders_status', 'service_reminders', ['status'])
