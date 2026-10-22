"""Cria as colunas novas da O.S. (desconto, tipo de atendimento, problema, laudo, observações ao cliente).

Idempotente: só adiciona o que falta. Se o banco usa Alembic e está na revisão anterior, marca a nova
(20261021_18) para que um `db upgrade` futuro não tente criar as colunas de novo.
Uso: python scripts/add_work_order_details.py [caminho-do-banco-sqlite]   (sem argumento usa o .env)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.schema import CreateColumn  # noqa: E402

from app import create_app  # noqa: E402
from app.models import WorkOrder, db  # noqa: E402

NEW_COLUMNS = ('desconto', 'tipo_atendimento', 'problema_relatado', 'laudo', 'observacoes_cliente')
PREVIOUS, CURRENT = '20260924_17', '20261021_18'


def main(database_url=None):
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': database_url, 'AUTO_CREATE_SCHEMA': False} if database_url else None)
    with app.app_context():
        existing = {column['name'] for column in inspect(db.engine).get_columns('work_orders')}
        with db.engine.begin() as connection:
            for name in NEW_COLUMNS:
                if name in existing:
                    print(f'já existe: {name}')
                    continue
                definition = CreateColumn(WorkOrder.__table__.c[name]).compile(dialect=db.engine.dialect)
                connection.execute(text(f'ALTER TABLE work_orders ADD COLUMN {definition}'))
                print(f'criada: {name}')
            if inspect(connection).has_table('alembic_version'):
                version = connection.execute(text('SELECT version_num FROM alembic_version')).scalar()
                if version == PREVIOUS:
                    connection.execute(text('UPDATE alembic_version SET version_num = :v'), {'v': CURRENT})
                    print(f'alembic: {PREVIOUS} -> {CURRENT}')
                else:
                    print(f'alembic na revisão {version}; não alterada')


if __name__ == '__main__':
    main(f'sqlite:///{sys.argv[1]}' if len(sys.argv) > 1 else None)
