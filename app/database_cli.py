"""Explicit adoption of a frozen baseline after checking a legacy database."""
import click
from flask_migrate import stamp
from sqlalchemy import inspect
from .models import db


def register_database_commands(app):
    @app.cli.command('seed')
    def seed_command():
        from .seeds import seed_database
        seed_database()
        click.echo('Dados iniciais verificados.')

    @app.cli.command('adotar-baseline')
    def adopt_baseline():
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        if 'alembic_version' in tables:
            revision = db.session.execute(db.text('SELECT version_num FROM alembic_version')).first()
            if revision:
                raise click.ClickException('Este banco já tem uma revisão Alembic. Use flask db upgrade.')
        missing = []
        for table in db.metadata.sorted_tables:
            if table.name not in tables:
                missing.append(table.name)
                continue
            columns = {column['name'] for column in inspector.get_columns(table.name)}
            missing.extend(f'{table.name}.{column.name}' for column in table.columns if column.name not in columns)
        if missing:
            raise click.ClickException('Baseline não adotada: faltam tabelas/colunas: ' + ', '.join(missing))
        # The check is structural presence, not a full constraint/type audit.
        stamp(revision='20260905_01')
        click.echo('Baseline adotada. Configure AUTO_CREATE_SCHEMA=false e use flask db upgrade nas próximas versões.')
