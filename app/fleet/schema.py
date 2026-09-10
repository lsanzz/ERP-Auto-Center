"""Additive compatibility bridge for installations using legacy startup bootstrap."""
from sqlalchemy import inspect, text
from ..models import db


def upgrade_legacy_vehicle_links():
    with db.engine.begin() as connection:
        inspector = inspect(connection)
        for name in ('work_orders', 'budgets'):
            columns = {column['name'] for column in inspector.get_columns(name)}
            if 'vehicle_id' not in columns:
                connection.execute(text(f'ALTER TABLE {name} ADD COLUMN vehicle_id INTEGER NULL'))
                if connection.dialect.name == 'mysql':
                    connection.execute(text(f'ALTER TABLE {name} ADD CONSTRAINT fk_{name}_vehicle_id FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)'))
            indexes = {index['name'] for index in inspect(connection).get_indexes(name)}
            if f'ix_{name}_vehicle_id' not in indexes:
                connection.execute(text(f'CREATE INDEX ix_{name}_vehicle_id ON {name} (vehicle_id)'))
