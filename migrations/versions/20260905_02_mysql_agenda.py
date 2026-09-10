"""MySQL agenda, workshop resources and yard workflow."""
from alembic import op
import sqlalchemy as sa

revision = '20260905_02'
down_revision = '20260905_01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('workshop_resources',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('nome', sa.String(100), nullable=False),
        sa.Column('tipo', sa.String(30), nullable=False), sa.Column('ativo', sa.Boolean(), nullable=False),
        sa.Column('observacoes', sa.Text()), sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('nome'), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    with op.batch_alter_table('work_orders') as batch:
        batch.add_column(sa.Column('promised_at', sa.DateTime()))
        batch.add_column(sa.Column('workshop_resource_id', sa.Integer()))
        batch.add_column(sa.Column('current_stage', sa.String(30), nullable=False, server_default='RECEPCAO'))
        batch.add_column(sa.Column('blocking_reason', sa.String(255)))
        batch.create_index('ix_work_orders_promised_at', ['promised_at'])
        batch.create_index('ix_work_orders_workshop_resource_id', ['workshop_resource_id'])
        batch.create_index('ix_work_orders_current_stage', ['current_stage'])
        batch.create_foreign_key('fk_work_orders_resource', 'workshop_resources', ['workshop_resource_id'], ['id'])
    op.create_table('appointments',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False), sa.Column('vehicle_id', sa.Integer()),
        sa.Column('employee_id', sa.Integer()), sa.Column('resource_id', sa.Integer()),
        sa.Column('work_order_id', sa.Integer()), sa.Column('start_at', sa.DateTime(), nullable=False),
        sa.Column('end_at', sa.DateTime(), nullable=False), sa.Column('status', sa.String(30), nullable=False),
        sa.Column('servico_previsto', sa.String(255), nullable=False), sa.Column('observacoes', sa.Text()),
        sa.Column('origem', sa.String(30), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False), sa.CheckConstraint('end_at > start_at'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id']), sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id']),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id']), sa.ForeignKeyConstraint(['resource_id'], ['workshop_resources.id']),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id']), sa.UniqueConstraint('work_order_id'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    for name, cols in [('client_id',['client_id']),('vehicle_id',['vehicle_id']),('employee_id',['employee_id']),('resource_id',['resource_id']),('status',['status']),('period',['start_at','end_at'])]:
        op.create_index(f'ix_appointments_{name}', 'appointments', cols)
    op.create_table('work_order_stage_history',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('work_order_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer()), sa.Column('stage', sa.String(30), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False), sa.Column('ended_at', sa.DateTime()),
        sa.Column('blocking_reason', sa.String(255)), sa.Column('observation', sa.Text()),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id']), sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_index('ix_work_order_stage_history_work_order_id', 'work_order_stage_history', ['work_order_id'])
    op.create_index('ix_work_order_stage_history_stage', 'work_order_stage_history', ['stage'])


def downgrade():
    op.drop_table('work_order_stage_history')
    op.drop_table('appointments')
    with op.batch_alter_table('work_orders') as batch:
        batch.drop_constraint('fk_work_orders_resource', type_='foreignkey')
        for name in ('ix_work_orders_current_stage','ix_work_orders_workshop_resource_id','ix_work_orders_promised_at'):
            batch.drop_index(name)
        for name in ('blocking_reason','current_stage','workshop_resource_id','promised_at'):
            batch.drop_column(name)
    op.drop_table('workshop_resources')
