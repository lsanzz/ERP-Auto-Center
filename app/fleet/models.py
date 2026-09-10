from datetime import date

from ..models import db, TimestampMixin, SerializableMixin


class Vehicle(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'vehicles'
    __table_args__ = (
        db.UniqueConstraint('client_id', 'placa', name='uq_vehicle_client_plate'),
        db.CheckConstraint('quilometragem IS NULL OR quilometragem >= 0', name='ck_vehicle_km'),
    )

    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False, index=True)
    placa = db.Column(db.String(10), index=True)
    descricao = db.Column(db.String(160), nullable=False)
    chassi = db.Column(db.String(30), index=True)
    renavam = db.Column(db.String(20))
    marca = db.Column(db.String(80))
    modelo = db.Column(db.String(100))
    versao = db.Column(db.String(100))
    ano_fabricacao = db.Column(db.Integer)
    ano_modelo = db.Column(db.Integer)
    motor = db.Column(db.String(80))
    combustivel = db.Column(db.String(40))
    cambio = db.Column(db.String(40))
    cor = db.Column(db.String(40))
    categoria = db.Column(db.String(40), nullable=False, default='AUTOMOVEL')
    quilometragem = db.Column(db.Integer)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    observacoes = db.Column(db.Text)

    __mapper_args__ = {'version_id_col': version}
    client = db.relationship('Client', backref=db.backref('vehicles', passive_deletes='all'))
    work_orders = db.relationship('WorkOrder', back_populates='vehicle')
    budgets = db.relationship('Budget', back_populates='vehicle')
    readings = db.relationship('OdometerReading', order_by='OdometerReading.recorded_on.desc()')
    ownership_history = db.relationship('VehicleOwnershipHistory', order_by='VehicleOwnershipHistory.id.desc()')


class OdometerReading(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'odometer_readings'
    __table_args__ = (db.CheckConstraint('quilometragem >= 0', name='ck_reading_km'),)
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False, index=True)
    quilometragem = db.Column(db.Integer, nullable=False)
    recorded_on = db.Column(db.Date, nullable=False, default=date.today)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    observacoes = db.Column(db.String(255))
    user = db.relationship('User')


class VehicleOwnershipHistory(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'vehicle_ownership_history'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False, index=True)
    previous_client_id = db.Column(db.Integer, db.ForeignKey('clients.id'))
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    client = db.relationship('Client', foreign_keys=[client_id])
    previous_client = db.relationship('Client', foreign_keys=[previous_client_id])
