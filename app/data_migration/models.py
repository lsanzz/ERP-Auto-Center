from datetime import datetime

from ..models import db, TimestampMixin


class DataMigration(db.Model, TimestampMixin):
    __tablename__ = 'data_migrations'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    storage_name = db.Column(db.String(80), nullable=False)
    entity = db.Column(db.String(30), nullable=False)
    source = db.Column(db.String(80), nullable=False)
    options_json = db.Column(db.Text, nullable=False, default='{}')
    headers_json = db.Column(db.Text, nullable=False, default='[]')
    mapping_json = db.Column(db.Text, nullable=False, default='{}')
    status = db.Column(db.String(20), nullable=False, default='PREPARANDO', index=True)
    total = db.Column(db.Integer, nullable=False, default=0)
    processed = db.Column(db.Integer, nullable=False, default=0)
    imported = db.Column(db.Integer, nullable=False, default=0)
    skipped = db.Column(db.Integer, nullable=False, default=0)
    errors = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.String(500))


class MigrationRow(db.Model):
    __tablename__ = 'migration_rows'
    migration_id = db.Column(db.Integer, db.ForeignKey('data_migrations.id'), primary_key=True)
    number = db.Column(db.Integer, primary_key=True)
    payload = db.Column(db.Text, nullable=False)
    result = db.Column(db.String(20), nullable=False, default='PENDENTE')
    message = db.Column(db.String(500))


class MigrationKey(db.Model):
    """Durable idempotency ledger; inserted in the same transaction as business data."""
    __tablename__ = 'migration_keys'
    digest = db.Column(db.String(64), primary_key=True)
    migration_id = db.Column(db.Integer, db.ForeignKey('data_migrations.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
