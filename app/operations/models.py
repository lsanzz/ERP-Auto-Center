from __future__ import annotations

from datetime import datetime

from ..models import SerializableMixin, TimestampMixin, db


class VehicleInspection(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'vehicle_inspections'

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False, unique=True)
    odometer = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False, default='RASCUNHO', index=True)
    notes = db.Column(db.Text)
    completed_at = db.Column(db.DateTime)
    completed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    work_order = db.relationship('WorkOrder', back_populates='inspection')
    completed_by = db.relationship('User')
    items = db.relationship('InspectionItem', back_populates='inspection', cascade='all, delete-orphan', order_by='InspectionItem.id')
    photos = db.relationship('InspectionPhoto', back_populates='inspection', cascade='all, delete-orphan', order_by='InspectionPhoto.id')


class InspectionItem(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'inspection_items'

    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey('vehicle_inspections.id'), nullable=False, index=True)
    area = db.Column(db.String(60), nullable=False)
    description = db.Column(db.String(160), nullable=False)
    condition = db.Column(db.String(20), nullable=False, default='NAO_VERIFICADO')
    notes = db.Column(db.String(255))

    inspection = db.relationship('VehicleInspection', back_populates='items')


class InspectionPhoto(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'inspection_photos'

    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey('vehicle_inspections.id'), nullable=False, index=True)
    storage_name = db.Column(db.String(255), nullable=False, unique=True)
    original_name = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    caption = db.Column(db.String(255))

    inspection = db.relationship('VehicleInspection', back_populates='photos')


class BudgetApproval(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'budget_approvals'

    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default='PENDENTE', index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    responded_at = db.Column(db.DateTime)
    response_name = db.Column(db.String(160))
    response_document = db.Column(db.String(30))
    response_note = db.Column(db.Text)
    response_ip = db.Column(db.String(64))
    response_user_agent = db.Column(db.String(255))
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    revision_id = db.Column(db.Integer, db.ForeignKey('budget_revisions.id'), index=True)
    approved_total = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default='0')

    budget = db.relationship('Budget', back_populates='approvals')
    created_by = db.relationship('User')
    revision = db.relationship('BudgetRevision')
    item_decisions = db.relationship('BudgetApprovalItem', back_populates='approval', cascade='all, delete-orphan')


class BudgetRevision(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'budget_revisions'

    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=False, index=True)
    revision_number = db.Column(db.Integer, nullable=False)
    snapshot_json = db.Column(db.Text, nullable=False)
    total = db.Column(db.Numeric(12, 2), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    __table_args__ = (db.UniqueConstraint('budget_id', 'revision_number', name='uq_budget_revision_number'),)


class BudgetApprovalItem(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'budget_approval_items'

    id = db.Column(db.Integer, primary_key=True)
    approval_id = db.Column(db.Integer, db.ForeignKey('budget_approvals.id', ondelete='CASCADE'), nullable=False, index=True)
    budget_item_id = db.Column(db.Integer, db.ForeignKey('budget_items.id'), nullable=False)
    description_snapshot = db.Column(db.String(255), nullable=False)
    total_snapshot = db.Column(db.Numeric(12, 2), nullable=False)
    decision = db.Column(db.String(20), nullable=False, default='PENDENTE')

    approval = db.relationship('BudgetApproval', back_populates='item_decisions')
    budget_item = db.relationship('BudgetItem')


class StockReservation(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'stock_reservations'

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False, index=True)
    work_order_item_id = db.Column(db.Integer, db.ForeignKey('work_order_items.id', ondelete='CASCADE'), nullable=False, unique=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    quantity = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='ATIVA', index=True)
    consumed_at = db.Column(db.DateTime)
    released_at = db.Column(db.DateTime)

    work_order = db.relationship('WorkOrder', back_populates='stock_reservations')
    work_order_item = db.relationship('WorkOrderItem', back_populates='stock_reservation')
    product = db.relationship('Product', back_populates='stock_reservations')


class InventoryMovement(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'inventory_movements'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), index=True)
    movement_type = db.Column(db.String(30), nullable=False, index=True)
    quantity = db.Column(db.Numeric(12, 2), nullable=False)
    balance_after = db.Column(db.Numeric(12, 2), nullable=False)
    reference = db.Column(db.String(100))
    notes = db.Column(db.String(255))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    stock_location_id = db.Column(db.Integer, db.ForeignKey('stock_locations.id'), index=True)
    unit_cost = db.Column(db.Numeric(12, 2))
    reversal_of_id = db.Column(db.Integer, db.ForeignKey('inventory_movements.id'), unique=True)

    product = db.relationship('Product', back_populates='inventory_movements')
    work_order = db.relationship('WorkOrder', back_populates='inventory_movements')
    user = db.relationship('User')
    stock_location = db.relationship('StockLocation')
    reversal_of = db.relationship('InventoryMovement', remote_side='InventoryMovement.id', uselist=False)


class ServiceWarranty(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'service_warranties'

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False, unique=True)
    starts_at = db.Column(db.Date, nullable=False)
    ends_at = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='ATIVA', index=True)
    terms = db.Column(db.Text)

    work_order = db.relationship('WorkOrder', back_populates='warranty')


class AuditEvent(db.Model, SerializableMixin):
    __tablename__ = 'audit_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    action = db.Column(db.String(40), nullable=False, index=True)
    entity_type = db.Column(db.String(60), nullable=False, index=True)
    entity_id = db.Column(db.Integer, index=True)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)

    user = db.relationship('User')
