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
        return raw_url.replace('postgres://', 'postgresql://', 1)
    return raw_url


def _run_schema_updates(app: Flask) -> None:
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    if 'work_orders' not in table_names:
        return

    columns = {column['name'] for column in inspector.get_columns('work_orders')}
    statements = []
    if 'client_nome' not in columns:
        statements.append("ALTER TABLE work_orders ADD COLUMN client_nome VARCHAR(160)")
    if 'emitir_nota' not in columns:
        if db.engine.dialect.name == 'postgresql':
            statements.append("ALTER TABLE work_orders ADD COLUMN emitir_nota BOOLEAN NOT NULL DEFAULT FALSE")
        else:
            statements.append("ALTER TABLE work_orders ADD COLUMN emitir_nota BOOLEAN NOT NULL DEFAULT 0")
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

        return {
            'format_currency': format_currency,
            'iso_today': iso_today,
            'current_user': current_user,
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