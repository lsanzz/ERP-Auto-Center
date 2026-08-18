from pathlib import Path
import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from sqlalchemy import inspect, text

from .models import db
from .seeds import seed_database
from .utils import date_br, datetime_br, format_currency, iso_today


def _normalize_database_url(raw_url: str | None, instance_path: Path) -> str:
    if not raw_url:
        return f"sqlite:///{instance_path / 'erp_auto_center.db'}"
    if raw_url.startswith('postgres://'):
        return raw_url.replace('postgres://', 'postgresql+psycopg://', 1)
    if raw_url.startswith('postgresql+psycopg2://'):
        return raw_url.replace('postgresql+psycopg2://', 'postgresql+psycopg://', 1)
    if raw_url.startswith('postgresql://'):
        return raw_url.replace('postgresql://', 'postgresql+psycopg://', 1)
    return raw_url


def _run_schema_updates(app: Flask) -> None:
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    if 'work_orders' not in table_names:
        return

    statements = []
    columns = {column['name'] for column in inspector.get_columns('work_orders')}
    if 'client_nome' not in columns:
        statements.append("ALTER TABLE work_orders ADD COLUMN client_nome VARCHAR(160)")
    if 'emitir_nota' not in columns:
        if db.engine.dialect.name == 'postgresql':
            statements.append("ALTER TABLE work_orders ADD COLUMN emitir_nota BOOLEAN NOT NULL DEFAULT FALSE")
        else:
            statements.append("ALTER TABLE work_orders ADD COLUMN emitir_nota BOOLEAN NOT NULL DEFAULT 0")
    if 'estoque_baixado' not in columns:
        if db.engine.dialect.name == 'postgresql':
            statements.append("ALTER TABLE work_orders ADD COLUMN estoque_baixado BOOLEAN NOT NULL DEFAULT FALSE")
        else:
            statements.append("ALTER TABLE work_orders ADD COLUMN estoque_baixado BOOLEAN NOT NULL DEFAULT 0")

    if 'products' in table_names:
        product_columns = {column['name'] for column in inspector.get_columns('products')}
        if 'estoque_atual' not in product_columns:
            statements.append("ALTER TABLE products ADD COLUMN estoque_atual NUMERIC(12, 2) NOT NULL DEFAULT 0")
        if 'estoque_minimo' not in product_columns:
            statements.append("ALTER TABLE products ADD COLUMN estoque_minimo NUMERIC(12, 2) NOT NULL DEFAULT 0")

    if 'xml_invoice_imports' in table_names:
        xml_columns = {column['name'] for column in inspector.get_columns('xml_invoice_imports')}
        if 'raw_xml' not in xml_columns:
            statements.append("ALTER TABLE xml_invoice_imports ADD COLUMN raw_xml TEXT")

    for sql in statements:
        db.session.execute(text(sql))
    if statements:
        db.session.commit()


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)

    database_url = _normalize_database_url(os.getenv('DATABASE_URL'), instance_path)

    app.config.update(
        SECRET_KEY=os.getenv('SECRET_KEY', 'erp-auto-center-secret'),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={
            'pool_pre_ping': True,
        },
    )

    if test_config:
        app.config.update(test_config)

    db.init_app(app)

    @app.template_filter('date_br')
    def _date_br(value):
        return date_br(value)

    @app.template_filter('datetime_br')
    def _datetime_br(value):
        return datetime_br(value)

    @app.context_processor
    def utility_context():
        from .auth import current_user
        from .settings import get_system_settings

        return {
            'format_currency': format_currency,
            'iso_today': iso_today,
            'current_user': current_user,
            'system_settings': get_system_settings(),
        }

    from .web import web_bp
    from .api import api_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix='/api')

    with app.app_context():
        db.create_all()
        _run_schema_updates(app)
        if os.getenv("RUN_DB_SEED", "false").lower() == "true":
            seed_database()

    return app
