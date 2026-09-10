from ..models import db, TimestampMixin, SerializableMixin


class WorkshopResource(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'workshop_resources'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    tipo = db.Column(db.String(30), nullable=False, default='BOX')
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    observacoes = db.Column(db.Text)


class Appointment(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'appointments'
    __table_args__ = (
        db.CheckConstraint('end_at > start_at', name='ck_appointment_period'),
        db.Index('ix_appointment_period', 'start_at', 'end_at'),
    )
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False, index=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), index=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('workshop_resources.id'), index=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), unique=True)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(30), nullable=False, default='AGENDADO', index=True)
    servico_previsto = db.Column(db.String(255), nullable=False)
    observacoes = db.Column(db.Text)
    origem = db.Column(db.String(30), nullable=False, default='INTERNO')
    __mapper_args__ = {'version_id_col': version}
    client = db.relationship('Client')
    vehicle = db.relationship('Vehicle')
    employee = db.relationship('Employee')
    resource = db.relationship('WorkshopResource')
    work_order = db.relationship('WorkOrder')


class WorkOrderStageHistory(db.Model, SerializableMixin):
    __tablename__ = 'work_order_stage_history'
    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    stage = db.Column(db.String(30), nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime)
    blocking_reason = db.Column(db.String(255))
    observation = db.Column(db.Text)
    user = db.relationship('User')
    work_order = db.relationship('WorkOrder', back_populates='stage_history')
