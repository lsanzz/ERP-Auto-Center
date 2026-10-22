from pathlib import Path
import logging
import os
import secrets
import time
from dotenv import load_dotenv
load_dotenv()

# date.today()/datetime.now() são usados em todo o sistema: o "hoje" é sempre o da oficina, não o do servidor.
os.environ.setdefault('TZ', 'America/Sao_Paulo')
if hasattr(time, 'tzset'):
    time.tzset()

from flask import Flask, send_from_directory
from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn

from .models import db
from .seeds import seed_database
from .utils import date_br, datetime_br, format_currency, iso_today


def _normalize_database_url(raw_url: str | None, instance_path: Path) -> str:
    if not raw_url:
        raise RuntimeError('Configure DATABASE_URL para MySQL (mysql+pymysql://...).')
    from sqlalchemy.engine import make_url
    url = make_url(raw_url)
    if url.get_backend_name() != 'mysql':
        raise RuntimeError('A aplicação requer MySQL. SQLite é permitido apenas em testes explícitos.')
    return url.set(drivername='mysql+pymysql').update_query_dict({'charset': 'utf8mb4'}).render_as_string(hide_password=False)


def _run_schema_updates(app: Flask) -> None:
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    if 'work_orders' not in table_names:
        return

    statements = []
    from .models import FiscalApiConfig, SystemSettings, UniNFeSubmission, WorkOrder
    for model in (SystemSettings, FiscalApiConfig, UniNFeSubmission, WorkOrder):
        table_name = model.__tablename__
        if table_name not in table_names:
            continue
        current_columns = {column['name'] for column in inspector.get_columns(table_name)}
        for column in model.__table__.columns:
            if column.name not in current_columns:
                definition = str(CreateColumn(column).compile(dialect=db.engine.dialect))
                statements.append(f'ALTER TABLE {table_name} ADD COLUMN {definition}')
    columns = {column['name'] for column in inspector.get_columns('work_orders')}
    
    if 'client_nome' not in columns:
        statements.append("ALTER TABLE work_orders ADD COLUMN client_nome VARCHAR(160)")
    if 'emitir_nota' not in columns:
        statements.append("ALTER TABLE work_orders ADD COLUMN emitir_nota BOOLEAN NOT NULL DEFAULT 0")
    if 'estoque_baixado' not in columns:
        statements.append("ALTER TABLE work_orders ADD COLUMN estoque_baixado BOOLEAN NOT NULL DEFAULT 0")
            
    # Controle otimista de concorrência — detecta edições simultâneas na mesma OS
    if 'version' not in columns:
        statements.append("ALTER TABLE work_orders ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
    if 'promised_at' not in columns:
        statements.append("ALTER TABLE work_orders ADD COLUMN promised_at DATETIME NULL")
    if 'workshop_resource_id' not in columns:
        statements.append("ALTER TABLE work_orders ADD COLUMN workshop_resource_id INTEGER NULL")
    if 'current_stage' not in columns:
        statements.append("ALTER TABLE work_orders ADD COLUMN current_stage VARCHAR(30) NOT NULL DEFAULT 'RECEPCAO'")
    if 'blocking_reason' not in columns:
        statements.append("ALTER TABLE work_orders ADD COLUMN blocking_reason VARCHAR(255) NULL")
    index_names = {index['name'] for index in inspector.get_indexes('work_orders')}
    for column in ('promised_at', 'workshop_resource_id', 'current_stage'):
        index_name = f'ix_work_orders_{column}'
        if index_name not in index_names:
            statements.append(f'CREATE INDEX {index_name} ON work_orders ({column})')
    if db.engine.dialect.name == 'mysql':
        foreign_keys = {fk.get('name') for fk in inspector.get_foreign_keys('work_orders')}
        if 'fk_work_orders_resource' not in foreign_keys:
            statements.append('ALTER TABLE work_orders ADD CONSTRAINT fk_work_orders_resource FOREIGN KEY (workshop_resource_id) REFERENCES workshop_resources(id)')

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
            if db.engine.dialect.name == 'mysql':
                # Sintaxe específica para o MySQL aceitar valores nulos (Corrigida no lugar certo)
                statements.append('ALTER TABLE fiscal_documents MODIFY work_order_id INTEGER NULL')
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


def _persistent_secret_key(instance_path: Path) -> str:
    """SECRET_KEY estável entre processos quando o .env não define uma.

    Uma chave aleatória por processo derruba sessões e CSRF sob Passenger/gunicorn, que
    rodam vários processos e reiniciam com frequência. O primeiro processo cria o arquivo
    de forma atômica; os demais leem a mesma chave.
    """
    key_file = instance_path / 'secret_key'
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        for _ in range(100):  # outro processo pode estar terminando de gravar
            key = key_file.read_text(encoding='utf-8').strip()
            if key:
                return key
            time.sleep(0.02)
        raise RuntimeError(f'{key_file} está vazio; apague o arquivo ou defina SECRET_KEY no .env.')
    except OSError as exc:
        # Pasta sem permissão de escrita: o app sobe, mas as sessões não sobrevivem a reinícios.
        logging.getLogger(__name__).warning('secret_key_not_persisted path=%s error=%s', key_file, exc)
        return secrets.token_hex(32)
    key = secrets.token_hex(32)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(key)
    return key


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)

    explicit = (test_config or {}).get('SQLALCHEMY_DATABASE_URI')
    if explicit and (test_config or {}).get('TESTING') and str(explicit).startswith('sqlite:'):
        database_url = explicit
    else:
        database_url = _normalize_database_url(explicit or os.getenv('DATABASE_URL'), instance_path)

    is_mysql = database_url.startswith('mysql')

    engine_options: dict = {
        'pool_pre_ping': True, 
    }
    if is_mysql:
        # MySQL/InnoDB: conexões verificadas e recicladas.
        engine_options.update({
            'pool_size': 10,       
            'max_overflow': 20,    
            'pool_recycle': 300,   # Essencial para não cair no cPanel
            'pool_timeout': 30,    
        })

    secret_key = os.getenv('SECRET_KEY') or (test_config or {}).get('SECRET_KEY')
    if not secret_key:
        testing = (test_config or {}).get('TESTING')
        secret_key = secrets.token_hex(32) if testing else _persistent_secret_key(instance_path)

    app.config.update(
        APP_ENV=os.getenv('APP_ENV', 'development'),
        SECRET_KEY=secret_key,
        TRUSTED_HOSTS=os.getenv('TRUSTED_HOSTS', ''),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ECHO=False,  # nunca logar SQL em produção (performance)
        SQLALCHEMY_ENGINE_OPTIONS=engine_options,
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,
        SUPPORT_WHATSAPP=os.getenv('SUPPORT_WHATSAPP', ''),
        SUPPORT_EMAIL=os.getenv('SUPPORT_EMAIL', ''),
        ASYNC_EXTERNAL_CALLS=os.getenv('ASYNC_EXTERNAL_CALLS', 'false').lower() == 'true',
        UNINFE_TRANSPORT=os.getenv('UNINFE_TRANSPORT', 'local'),
        UNINFE_CONNECTOR_ID=os.getenv('UNINFE_CONNECTOR_ID', ''),
        UNINFE_CONNECTOR_TOKEN=os.getenv('UNINFE_CONNECTOR_TOKEN', ''),
        TURNSTILE_SITE_KEY=os.getenv('TURNSTILE_SITE_KEY'),
        TURNSTILE_SECRET_KEY=os.getenv('TURNSTILE_SECRET_KEY'),
    )

    if test_config:
        app.config.update(test_config)
    if app.config.get('APP_ENV') == 'development':
        # Official Cloudflare keys: always-pass widget for localhost only.
        app.config['TURNSTILE_SITE_KEY'] = app.config.get('TURNSTILE_SITE_KEY') or '1x00000000000000000000AA'
        app.config['TURNSTILE_SECRET_KEY'] = app.config.get('TURNSTILE_SECRET_KEY') or '1x0000000000000000000000000000000AA'
    app.config['TURNSTILE_ENABLED'] = bool(
        not app.config.get('TESTING')
        and app.config.get('TURNSTILE_SITE_KEY')
        and app.config.get('TURNSTILE_SECRET_KEY')
    )
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url

    from .data_migration.routes import configure_upload_limit
    configure_upload_limit(app)
    from .security import configure_security
    configure_security(app)
    proxies = int(os.getenv('TRUSTED_PROXY_COUNT') or 0)
    if proxies > 0:
        # Atrás de Cloudflare/proxy o remote_addr seria o do proxy e um usuário bloquearia o login de todos.
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies)
    from .observability import configure_observability
    configure_observability(app)

    db.init_app(app)
    from .fleet import models as fleet_models
    from .scheduling import models as scheduling_models
    from .operations import models as operations_models
    from .operations.audit import configure_automatic_audit
    configure_automatic_audit()
    for table in db.metadata.tables.values():
        table.dialect_options['mysql'].update(engine='InnoDB', charset='utf8mb4')
    from flask_migrate import Migrate
    Migrate(app, db, render_as_batch=True, compare_type=True)
    from .database_cli import register_database_commands
    register_database_commands(app)
    from .jobs import register_job_commands
    register_job_commands(app)
    from .data_migration.worker import configure_worker
    configure_worker(app)

    @app.get('/service-worker.js')
    def service_worker():
        return send_from_directory(app.static_folder, 'service-worker.js', mimetype='application/javascript')

    @app.template_filter('date_br')
    def _date_br(value):
        return date_br(value)

    @app.template_filter('datetime_br')
    def _datetime_br(value):
        return datetime_br(value)

    @app.context_processor
    def utility_context():
        from .auth import current_user, has_permission
        from .settings import get_system_settings

        return {
            'format_currency': format_currency,
            'iso_today': iso_today,
            'current_user': current_user,
            'can': has_permission,
            'system_settings': get_system_settings(),
        }

    from .web import web_bp
    from .api import api_bp

    app.register_blueprint(web_bp)
    from .data_migration.routes import migration_bp
    app.register_blueprint(migration_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    from .uninfe_relay import relay_bp
    app.register_blueprint(relay_bp)
    # Dedicated bearer authentication; never accepts browser session cookies.
    app.extensions['csrf'].exempt(relay_bp)
    from .fleet.routes import fleet_bp
    app.register_blueprint(fleet_bp)
    from .scheduling.routes import scheduling_bp
    app.register_blueprint(scheduling_bp)
    from .operations.routes import operations_bp
    app.register_blueprint(operations_bp)
    from .management import management_bp
    app.register_blueprint(management_bp)
    from .business_reports import business_bp
    app.register_blueprint(business_bp)
    from .assistant.routes import assistant_bp
    app.register_blueprint(assistant_bp)
    from .lgpd import lgpd_bp
    app.register_blueprint(lgpd_bp)
    from .system_admin import register_system_admin_cli, system_admin_bp
    app.register_blueprint(system_admin_bp)
    register_system_admin_cli(app)

    # Explicit migrations are opt-in during the transition from the legacy bootstrap.
    # Tests and migration commands can disable every startup schema mutation.
    if app.config.get('AUTO_CREATE_SCHEMA', os.getenv('AUTO_CREATE_SCHEMA', 'false').lower() == 'true'):
        with app.app_context():
            db.create_all()
            _run_schema_updates(app)
            from .fleet.schema import upgrade_legacy_vehicle_links
            upgrade_legacy_vehicle_links()
            if os.getenv("RUN_DB_SEED", "false").lower() == "true":
                seed_database()

    return app
