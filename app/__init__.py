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

    is_pg = db.engine.dialect.name == 'postgresql'
    statements = []
    columns = {column['name'] for column in inspector.get_columns('work_orders')}
    if 'client_nome' not in columns:
        statements.append("ALTER TABLE work_orders ADD COLUMN client_nome VARCHAR(160)")
    if 'emitir_nota' not in columns:
        if is_pg:
            statements.append("ALTER TABLE work_orders ADD COLUMN emitir_nota BOOLEAN NOT NULL DEFAULT FALSE")
        else:
            statements.append("ALTER TABLE work_orders ADD COLUMN emitir_nota BOOLEAN NOT NULL DEFAULT 0")
    if 'estoque_baixado' not in columns:
        if is_pg:
            statements.append("ALTER TABLE work_orders ADD COLUMN estoque_baixado BOOLEAN NOT NULL DEFAULT FALSE")
        else:
            statements.append("ALTER TABLE work_orders ADD COLUMN estoque_baixado BOOLEAN NOT NULL DEFAULT 0")
    # Controle otimista de concorrência — detecta edições simultâneas na mesma OS
    if 'version' not in columns:
        statements.append("ALTER TABLE work_orders ADD COLUMN version INTEGER NOT NULL DEFAULT 0")

    if 'products' in table_names:
        product_columns = {column['name'] for column in inspector.get_columns('products')}
        if 'estoque_atual' not in product_columns:
            statements.append("ALTER TABLE products ADD COLUMN estoque_atual NUMERIC(12, 2) NOT NULL DEFAULT 0")
        if 'estoque_minimo' not in product_columns:
            statements.append("ALTER TABLE products ADD COLUMN estoque_minimo NUMERIC(12, 2) NOT NULL DEFAULT 0")
        if 'ncm' not in product_columns:
            statements.append("ALTER TABLE products ADD COLUMN ncm VARCHAR(20)")
        if 'cfop' not in product_columns:
            statements.append("ALTER TABLE products ADD COLUMN cfop VARCHAR(10)")

    if 'xml_invoice_imports' in table_names:
        xml_columns = {column['name'] for column in inspector.get_columns('xml_invoice_imports')}
        if 'raw_xml' not in xml_columns:
            statements.append("ALTER TABLE xml_invoice_imports ADD COLUMN raw_xml TEXT")

    if 'fiscal_documents' in table_names:
        fiscal_columns = {column['name']: column for column in inspector.get_columns('fiscal_documents')}
        work_order_column = fiscal_columns.get('work_order_id')
        if work_order_column and not work_order_column.get('nullable', True):
            if is_pg:
                statements.append('ALTER TABLE fiscal_documents ALTER COLUMN work_order_id DROP NOT NULL')
            elif db.engine.dialect.name == 'sqlite':
                with db.engine.begin() as connection:
                    connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
                    connection.exec_driver_sql('ALTER TABLE fiscal_documents RENAME TO fiscal_documents_old')
                    connection.exec_driver_sql('''
                        CREATE TABLE fiscal_documents (
                            id INTEGER PRIMARY KEY,
                            work_order_id INTEGER,
                            provider_name VARCHAR(80) NOT NULL DEFAULT 'CUSTOM',
                            document_type VARCHAR(20) NOT NULL DEFAULT 'NFSE',
                            environment VARCHAR(20) NOT NULL DEFAULT 'HOMOLOGACAO',
                            status VARCHAR(30) NOT NULL DEFAULT 'RASCUNHO',
                            numero VARCHAR(30), serie VARCHAR(20), external_id VARCHAR(80),
                            access_key VARCHAR(80), request_payload TEXT, response_payload TEXT,
                            xml_content TEXT, pdf_url VARCHAR(255), error_message TEXT,
                            created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                            FOREIGN KEY(work_order_id) REFERENCES work_orders(id)
                        )
                    ''')
                    connection.exec_driver_sql('''
                        INSERT INTO fiscal_documents
                        SELECT id, work_order_id, provider_name, document_type, environment, status,
                               numero, serie, external_id, access_key, request_payload, response_payload,
                               xml_content, pdf_url, error_message, created_at, updated_at
                        FROM fiscal_documents_old
                    ''')
                    connection.exec_driver_sql('DROP TABLE fiscal_documents_old')
                    connection.exec_driver_sql('PRAGMA foreign_keys=ON')

    # Controle otimista — budgets
    if 'budgets' in table_names:
        budget_columns = {column['name'] for column in inspector.get_columns('budgets')}
        if 'version' not in budget_columns:
            statements.append("ALTER TABLE budgets ADD COLUMN version INTEGER NOT NULL DEFAULT 0")

    # Controle otimista — financial_entries
    if 'financial_entries' in table_names:
        fe_columns = {column['name'] for column in inspector.get_columns('financial_entries')}
        if 'version' not in fe_columns:
            statements.append("ALTER TABLE financial_entries ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
        # Campos de liquidação detalhada
        if 'valor_baixa' not in fe_columns:
            statements.append("ALTER TABLE financial_entries ADD COLUMN valor_baixa NUMERIC(12, 2)")
        if 'juros' not in fe_columns:
            statements.append("ALTER TABLE financial_entries ADD COLUMN juros NUMERIC(12, 2) DEFAULT 0")
        if 'desconto' not in fe_columns:
            statements.append("ALTER TABLE financial_entries ADD COLUMN desconto NUMERIC(12, 2) DEFAULT 0")
        if 'taxa' not in fe_columns:
            statements.append("ALTER TABLE financial_entries ADD COLUMN taxa NUMERIC(12, 2) DEFAULT 0")
        if 'acrescimo' not in fe_columns:
            statements.append("ALTER TABLE financial_entries ADD COLUMN acrescimo NUMERIC(12, 2) DEFAULT 0")
        if 'observacoes_pagamento' not in fe_columns:
            statements.append("ALTER TABLE financial_entries ADD COLUMN observacoes_pagamento TEXT")

    for sql in statements:
        db.session.execute(text(sql))
    if statements:
        db.session.commit()


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)

    database_url = _normalize_database_url(os.getenv('DATABASE_URL'), instance_path)

    is_postgres = database_url.startswith('postgresql')

    engine_options: dict = {
        'pool_pre_ping': True,  # verifica conexão antes de usar (evita broken pipe)
    }
    if is_postgres:
        # Pool robusto para múltiplos usuários simultâneos
        engine_options.update({
            'pool_size': 10,       # conexões permanentes no pool
            'max_overflow': 20,    # conexões extras permitidas em pico
            'pool_recycle': 300,   # reciclar a cada 5 min (evita timeout do Render)
            'pool_timeout': 30,    # timeout ao aguardar conexão disponível
        })

    app.config.update(
        SECRET_KEY=os.getenv('SECRET_KEY', 'erp-auto-center-secret'),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ECHO=False,  # nunca logar SQL em produção (performance)
        SQLALCHEMY_ENGINE_OPTIONS=engine_options,
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
