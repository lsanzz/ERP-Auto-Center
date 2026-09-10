"""Digital inspections, approvals, stock ledger and after-sales."""
from alembic import op
import sqlalchemy as sa


revision = '20260906_03'
down_revision = '20260905_02'
branch_labels = None
depends_on = None


MYSQL = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'}


def timestamps():
    return [
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    ]


def upgrade():
    op.create_table('vehicle_inspections',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('work_order_id', sa.Integer(), nullable=False),
        sa.Column('odometer', sa.Integer()), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('notes', sa.Text()), sa.Column('completed_at', sa.DateTime()),
        sa.Column('completed_by_id', sa.Integer()), *timestamps(),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], name='fk_inspection_order'),
        sa.ForeignKeyConstraint(['completed_by_id'], ['users.id'], name='fk_inspection_user'),
        sa.UniqueConstraint('work_order_id', name='uq_inspection_order'), **MYSQL)
    op.create_index('ix_vehicle_inspections_status', 'vehicle_inspections', ['status'])

    op.create_table('inspection_items',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('inspection_id', sa.Integer(), nullable=False),
        sa.Column('area', sa.String(60), nullable=False), sa.Column('description', sa.String(160), nullable=False),
        sa.Column('condition', sa.String(20), nullable=False), sa.Column('notes', sa.String(255)), *timestamps(),
        sa.ForeignKeyConstraint(['inspection_id'], ['vehicle_inspections.id'], name='fk_inspection_item'), **MYSQL)
    op.create_index('ix_inspection_items_inspection_id', 'inspection_items', ['inspection_id'])

    op.create_table('inspection_photos',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('inspection_id', sa.Integer(), nullable=False),
        sa.Column('storage_name', sa.String(255), nullable=False), sa.Column('original_name', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(100), nullable=False), sa.Column('caption', sa.String(255)), *timestamps(),
        sa.ForeignKeyConstraint(['inspection_id'], ['vehicle_inspections.id'], name='fk_inspection_photo'),
        sa.UniqueConstraint('storage_name', name='uq_inspection_photo_storage'), **MYSQL)
    op.create_index('ix_inspection_photos_inspection_id', 'inspection_photos', ['inspection_id'])

    op.create_table('budget_approvals',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('budget_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False), sa.Column('responded_at', sa.DateTime()),
        sa.Column('response_name', sa.String(160)), sa.Column('response_document', sa.String(30)),
        sa.Column('response_note', sa.Text()), sa.Column('response_ip', sa.String(64)),
        sa.Column('response_user_agent', sa.String(255)), sa.Column('created_by_id', sa.Integer()), *timestamps(),
        sa.ForeignKeyConstraint(['budget_id'], ['budgets.id'], name='fk_approval_budget'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name='fk_approval_user'),
        sa.UniqueConstraint('token_hash', name='uq_approval_token'), **MYSQL)
    op.create_index('ix_budget_approvals_budget_id', 'budget_approvals', ['budget_id'])
    op.create_index('ix_budget_approvals_status', 'budget_approvals', ['status'])
    op.create_index('ix_budget_approvals_expires_at', 'budget_approvals', ['expires_at'])

    op.create_table('stock_reservations',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('work_order_id', sa.Integer(), nullable=False),
        sa.Column('work_order_item_id', sa.Integer(), nullable=False), sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Numeric(12, 2), nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('consumed_at', sa.DateTime()), sa.Column('released_at', sa.DateTime()), *timestamps(),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], name='fk_reservation_order'),
        sa.ForeignKeyConstraint(['work_order_item_id'], ['work_order_items.id'], name='fk_reservation_item', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], name='fk_reservation_product'),
        sa.UniqueConstraint('work_order_item_id', name='uq_reservation_item'), **MYSQL)
    op.create_index('ix_stock_reservations_work_order_id', 'stock_reservations', ['work_order_id'])
    op.create_index('ix_stock_reservations_product_id', 'stock_reservations', ['product_id'])
    op.create_index('ix_stock_reservations_status', 'stock_reservations', ['status'])

    op.create_table('inventory_movements',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('work_order_id', sa.Integer()), sa.Column('movement_type', sa.String(30), nullable=False),
        sa.Column('quantity', sa.Numeric(12, 2), nullable=False), sa.Column('balance_after', sa.Numeric(12, 2), nullable=False),
        sa.Column('reference', sa.String(100)), sa.Column('notes', sa.String(255)), sa.Column('user_id', sa.Integer()), *timestamps(),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], name='fk_movement_product'),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], name='fk_movement_order'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_movement_user'), **MYSQL)
    op.create_index('ix_inventory_movements_product_id', 'inventory_movements', ['product_id'])
    op.create_index('ix_inventory_movements_work_order_id', 'inventory_movements', ['work_order_id'])
    op.create_index('ix_inventory_movements_movement_type', 'inventory_movements', ['movement_type'])

    op.create_table('service_warranties',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('work_order_id', sa.Integer(), nullable=False),
        sa.Column('starts_at', sa.Date(), nullable=False), sa.Column('ends_at', sa.Date(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('terms', sa.Text()), *timestamps(),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], name='fk_warranty_order'),
        sa.UniqueConstraint('work_order_id', name='uq_warranty_order'), **MYSQL)
    op.create_index('ix_service_warranties_ends_at', 'service_warranties', ['ends_at'])
    op.create_index('ix_service_warranties_status', 'service_warranties', ['status'])

    op.create_table('service_reminders',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('vehicle_id', sa.Integer()), sa.Column('work_order_id', sa.Integer()),
        sa.Column('due_date', sa.Date(), nullable=False), sa.Column('reminder_type', sa.String(40), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('notes', sa.String(255)),
        sa.Column('contacted_at', sa.DateTime()), *timestamps(),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name='fk_reminder_client'),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], name='fk_reminder_vehicle'),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], name='fk_reminder_order'), **MYSQL)
    op.create_index('ix_service_reminders_client_id', 'service_reminders', ['client_id'])
    op.create_index('ix_service_reminders_vehicle_id', 'service_reminders', ['vehicle_id'])
    op.create_index('ix_service_reminders_work_order_id', 'service_reminders', ['work_order_id'])
    op.create_index('ix_service_reminders_due_date', 'service_reminders', ['due_date'])
    op.create_index('ix_service_reminders_status', 'service_reminders', ['status'])

    op.create_table('audit_events',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('user_id', sa.Integer()),
        sa.Column('action', sa.String(40), nullable=False), sa.Column('entity_type', sa.String(60), nullable=False),
        sa.Column('entity_id', sa.Integer()), sa.Column('details', sa.Text()), sa.Column('ip_address', sa.String(64)),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_audit_user'), **MYSQL)
    for column in ('user_id', 'action', 'entity_type', 'entity_id', 'created_at'):
        op.create_index(f'ix_audit_events_{column}', 'audit_events', [column])


def downgrade():
    for table in ('audit_events', 'service_reminders', 'service_warranties', 'inventory_movements',
                  'stock_reservations', 'budget_approvals', 'inspection_photos', 'inspection_items',
                  'vehicle_inspections'):
        op.drop_table(table)
