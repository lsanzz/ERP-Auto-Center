"""Mudanças de banco da revisão de out/2026: assistant_states, assinatura em system_settings e
autenticador em system_admins.

Idempotente: só cria o que falta, então pode rodar de novo sem risco. Se o banco usa Alembic e está
em 20261021_18, marca 20261022_21 para um `db upgrade` futuro não repetir o trabalho.
Rode pelo campo "Execute python script" do Setup Python App (cPanel sem shell). Faça backup antes.
Uso: python scripts/apply_review_2026_10.py [caminho-do-banco-sqlite]   (sem argumento usa o .env)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.schema import CreateColumn  # noqa: E402

from app import create_app  # noqa: E402
from app.models import AssistantState, SystemAdmin, SystemSettings, db  # noqa: E402

NEW_COLUMNS = {
    SystemSettings: ('subscription_plan', 'subscription_paid_until', 'subscription_suspended'),
    SystemAdmin: ('mfa_secret_encrypted',),
}
PREVIOUS, CURRENT = '20261021_18', '20261022_21'


def main(database_url=None):
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': database_url, 'AUTO_CREATE_SCHEMA': False} if database_url else None)
    with app.app_context():
        inspector = inspect(db.engine)
        if not inspector.has_table(AssistantState.__tablename__):
            AssistantState.__table__.create(db.engine)
            print('criada: tabela assistant_states')
        else:
            print('já existe: tabela assistant_states')
        with db.engine.begin() as connection:
            for model, names in NEW_COLUMNS.items():
                existing = {column['name'] for column in inspector.get_columns(model.__tablename__)}
                for name in names:
                    if name in existing:
                        print(f'já existe: {model.__tablename__}.{name}')
                        continue
                    definition = CreateColumn(model.__table__.c[name]).compile(dialect=db.engine.dialect)
                    connection.execute(text(f'ALTER TABLE {model.__tablename__} ADD COLUMN {definition}'))
                    print(f'criada: {model.__tablename__}.{name}')
            if inspect(connection).has_table('alembic_version'):
                version = connection.execute(text('SELECT version_num FROM alembic_version')).scalar()
                if version == PREVIOUS:
                    connection.execute(text('UPDATE alembic_version SET version_num = :v'), {'v': CURRENT})
                    print(f'alembic: {PREVIOUS} -> {CURRENT}')
                else:
                    print(f'alembic na revisão {version}; não alterada')
        print('Pronto.')


if __name__ == '__main__':
    main(f'sqlite:///{sys.argv[1]}' if len(sys.argv) > 1 else None)
