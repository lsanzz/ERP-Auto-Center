"""Add management, approval revision, purchasing and reconciliation foundations."""
from alembic import op
import sqlalchemy as sa

revision = '20260909_08'
down_revision = '20260907_07'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('chart_of_accounts',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('parent_id', sa.Integer()),
        sa.Column('code', sa.String(30), nullable=False), sa.Column('name', sa.String(120), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False), sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['parent_id'], ['chart_of_accounts.id']), sa.UniqueConstraint('code'))
    op.create_table('cost_centers',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('code', sa.String(30), nullable=False),
        sa.Column('name', sa.String(120), nullable=False), sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False), sa.UniqueConstraint('code'))
    op.create_table('stock_locations',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('code', sa.String(30), nullable=False),
        sa.Column('name', sa.String(120), nullable=False), sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False), sa.UniqueConstraint('code'))
    op.create_table('budget_revisions',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('budget_id', sa.Integer(), nullable=False),
        sa.Column('revision_number', sa.Integer(), nullable=False), sa.Column('snapshot_json', sa.Text(), nullable=False),
        sa.Column('total', sa.Numeric(12,2), nullable=False), sa.Column('created_by_id', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['budget_id'], ['budgets.id']), sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.UniqueConstraint('budget_id', 'revision_number', name='uq_budget_revision_number'))
    op.create_index('ix_budget_revisions_budget_id', 'budget_revisions', ['budget_id'])
    with op.batch_alter_table('budget_items') as batch:
        batch.add_column(sa.Column('classification', sa.String(20), nullable=False, server_default='NECESSARIO'))
    with op.batch_alter_table('budget_approvals') as batch:
        batch.add_column(sa.Column('revision_id', sa.Integer()))
        batch.add_column(sa.Column('approved_total', sa.Numeric(12,2), nullable=False, server_default='0'))
        batch.create_foreign_key('fk_budget_approval_revision', 'budget_revisions', ['revision_id'], ['id'])
        batch.create_index('ix_budget_approvals_revision_id', ['revision_id'])
    op.create_table('budget_approval_items',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('approval_id', sa.Integer(), nullable=False),
        sa.Column('budget_item_id', sa.Integer(), nullable=False), sa.Column('description_snapshot', sa.String(255), nullable=False),
        sa.Column('total_snapshot', sa.Numeric(12,2), nullable=False), sa.Column('decision', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['approval_id'], ['budget_approvals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['budget_item_id'], ['budget_items.id']))
    op.create_index('ix_budget_approval_items_approval_id', 'budget_approval_items', ['approval_id'])
    with op.batch_alter_table('financial_entries') as batch:
        batch.add_column(sa.Column('issued_on', sa.Date(), nullable=True))
        batch.add_column(sa.Column('competence_on', sa.Date(), nullable=True))
        batch.add_column(sa.Column('chart_account_id', sa.Integer()))
        batch.add_column(sa.Column('cost_center_id', sa.Integer()))
        batch.create_foreign_key('fk_financial_chart_account', 'chart_of_accounts', ['chart_account_id'], ['id'])
        batch.create_foreign_key('fk_financial_cost_center', 'cost_centers', ['cost_center_id'], ['id'])
        batch.create_index('ix_financial_entries_competence_on', ['competence_on'])
        batch.create_index('ix_financial_entries_chart_account_id', ['chart_account_id'])
        batch.create_index('ix_financial_entries_cost_center_id', ['cost_center_id'])
    op.execute('UPDATE financial_entries SET issued_on=vencimento, competence_on=vencimento WHERE issued_on IS NULL OR competence_on IS NULL')
    with op.batch_alter_table('financial_entries') as batch:
        batch.alter_column('issued_on', existing_type=sa.Date(), nullable=False)
        batch.alter_column('competence_on', existing_type=sa.Date(), nullable=False)
    op.create_table('bank_transactions',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('bank_account_id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.String(120)), sa.Column('posted_on', sa.Date(), nullable=False),
        sa.Column('description', sa.String(255), nullable=False), sa.Column('amount', sa.Numeric(12,2), nullable=False),
        sa.Column('source', sa.String(20), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(['bank_account_id'], ['bank_accounts.id']),
        sa.UniqueConstraint('bank_account_id', 'external_id', name='uq_bank_transaction_external'))
    op.create_index('ix_bank_transactions_bank_account_id', 'bank_transactions', ['bank_account_id'])
    op.create_index('ix_bank_transactions_posted_on', 'bank_transactions', ['posted_on'])
    op.create_table('bank_reconciliations',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('bank_transaction_id', sa.Integer(), nullable=False, unique=True),
        sa.Column('financial_entry_id', sa.Integer(), nullable=False, unique=True), sa.Column('reconciled_by_id', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['bank_transaction_id'], ['bank_transactions.id']),
        sa.ForeignKeyConstraint(['financial_entry_id'], ['financial_entries.id']), sa.ForeignKeyConstraint(['reconciled_by_id'], ['users.id']))
    op.create_table('commission_rules',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('name', sa.String(120), nullable=False),
        sa.Column('applies_to', sa.String(20), nullable=False), sa.Column('calculation_type', sa.String(20), nullable=False),
        sa.Column('value', sa.Numeric(12,4), nullable=False), sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_table('commission_entries',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('rule_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False), sa.Column('work_order_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(12,2), nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['rule_id'], ['commission_rules.id']), sa.ForeignKeyConstraint(['employee_id'], ['employees.id']),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id']))
    op.create_index('ix_commission_entries_employee_id', 'commission_entries', ['employee_id'])
    op.create_index('ix_commission_entries_work_order_id', 'commission_entries', ['work_order_id'])
    op.create_table('purchase_requests',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('number', sa.String(30), nullable=False, unique=True),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('supplier_id', sa.Integer()), sa.Column('requested_by_id', sa.Integer()),
        sa.Column('notes', sa.Text()), sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id']), sa.ForeignKeyConstraint(['requested_by_id'], ['users.id']))
    op.create_index('ix_purchase_requests_status', 'purchase_requests', ['status'])
    op.create_table('purchase_request_items',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('purchase_request_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False), sa.Column('quantity', sa.Numeric(12,2), nullable=False),
        sa.Column('quoted_unit_cost', sa.Numeric(12,2)), sa.Column('received_quantity', sa.Numeric(12,2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['purchase_request_id'], ['purchase_requests.id']), sa.ForeignKeyConstraint(['product_id'], ['products.id']))
    op.create_index('ix_purchase_request_items_purchase_request_id', 'purchase_request_items', ['purchase_request_id'])
    op.create_table('inventory_counts',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('stock_location_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('counted_by_id', sa.Integer()), sa.Column('closed_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['stock_location_id'], ['stock_locations.id']), sa.ForeignKeyConstraint(['counted_by_id'], ['users.id']))
    op.create_table('inventory_count_items',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('inventory_count_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False), sa.Column('expected_quantity', sa.Numeric(12,2), nullable=False),
        sa.Column('counted_quantity', sa.Numeric(12,2)), sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(['inventory_count_id'], ['inventory_counts.id']),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']))
    with op.batch_alter_table('inventory_movements') as batch:
        batch.add_column(sa.Column('stock_location_id', sa.Integer()))
        batch.add_column(sa.Column('unit_cost', sa.Numeric(12,2)))
        batch.add_column(sa.Column('reversal_of_id', sa.Integer()))
        batch.create_foreign_key('fk_inventory_location', 'stock_locations', ['stock_location_id'], ['id'])
        batch.create_foreign_key('fk_inventory_reversal', 'inventory_movements', ['reversal_of_id'], ['id'])
        batch.create_index('ix_inventory_movements_stock_location_id', ['stock_location_id'])
        batch.create_unique_constraint('uq_inventory_movements_reversal_of', ['reversal_of_id'])
    op.create_table('async_jobs',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('job_type', sa.String(40), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False), sa.Column('available_at', sa.DateTime(), nullable=False),
        sa.Column('last_error', sa.Text()), sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_index('ix_async_jobs_job_type', 'async_jobs', ['job_type'])
    op.create_index('ix_async_jobs_status', 'async_jobs', ['status'])
    op.create_index('ix_async_jobs_available_at', 'async_jobs', ['available_at'])


def downgrade():
    op.drop_table('async_jobs')
    with op.batch_alter_table('inventory_movements') as batch:
        batch.drop_constraint('uq_inventory_movements_reversal_of', type_='unique')
        batch.drop_constraint('fk_inventory_reversal', type_='foreignkey'); batch.drop_constraint('fk_inventory_location', type_='foreignkey')
        batch.drop_index('ix_inventory_movements_stock_location_id'); batch.drop_column('reversal_of_id'); batch.drop_column('unit_cost'); batch.drop_column('stock_location_id')
    op.drop_table('inventory_count_items'); op.drop_table('inventory_counts'); op.drop_table('purchase_request_items'); op.drop_table('purchase_requests')
    op.drop_table('commission_entries'); op.drop_table('commission_rules'); op.drop_table('bank_reconciliations'); op.drop_table('bank_transactions')
    with op.batch_alter_table('financial_entries') as batch:
        batch.drop_constraint('fk_financial_cost_center', type_='foreignkey'); batch.drop_constraint('fk_financial_chart_account', type_='foreignkey')
        batch.drop_index('ix_financial_entries_cost_center_id'); batch.drop_index('ix_financial_entries_chart_account_id'); batch.drop_index('ix_financial_entries_competence_on')
        batch.drop_column('cost_center_id'); batch.drop_column('chart_account_id'); batch.drop_column('competence_on'); batch.drop_column('issued_on')
    op.drop_table('budget_approval_items')
    with op.batch_alter_table('budget_approvals') as batch:
        batch.drop_constraint('fk_budget_approval_revision', type_='foreignkey'); batch.drop_index('ix_budget_approvals_revision_id')
        batch.drop_column('approved_total'); batch.drop_column('revision_id')
    with op.batch_alter_table('budget_items') as batch: batch.drop_column('classification')
    op.drop_table('budget_revisions'); op.drop_table('stock_locations'); op.drop_table('cost_centers'); op.drop_table('chart_of_accounts')
