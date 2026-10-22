from __future__ import annotations

from datetime import date, datetime
import json
from decimal import Decimal

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.dialects.mysql import LONGTEXT
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()

# XMLs and immutable JSON snapshots can exceed MySQL TEXT's 64 KiB capacity.
# Keep portable TEXT on SQLite/PostgreSQL and preserve full artifacts on MySQL.
FISCAL_ARTIFACT_TEXT = db.Text().with_variant(LONGTEXT(), 'mysql', 'mariadb')


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class SerializableMixin:
    def to_dict(self) -> dict:
        data: dict = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if isinstance(value, (datetime, date)):
                data[column.name] = value.isoformat()
            elif isinstance(value, Decimal):
                data[column.name] = float(value)
            else:
                data[column.name] = value
        return data


class User(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default='MECANICO')
    nome = db.Column(db.String(120), nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    mfa_enabled = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    mfa_secret_encrypted = db.Column(db.Text)

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)


class SystemAdmin(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'system_admins'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=False, default='Dono do sistema')
    active = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    last_login_at = db.Column(db.DateTime)

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)


class ManagedCompany(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'managed_companies'

    id = db.Column(db.Integer, primary_key=True)
    focus_company_id = db.Column(db.String(80), unique=True, nullable=False)
    document = db.Column(db.String(20), index=True)
    legal_name = db.Column(db.String(160))
    trade_name = db.Column(db.String(160))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    city = db.Column(db.String(100))
    state = db.Column(db.String(2))
    remote_status = db.Column(db.String(40))
    certificate_expires_at = db.Column(db.DateTime)
    remote_active = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    last_synced_at = db.Column(db.DateTime, nullable=False, default=datetime.now)


class SystemSettings(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'system_settings'

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(160), nullable=False, default='Japa Auto Center')
    trade_name = db.Column(db.String(160))
    company_document = db.Column(db.String(20))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))
    city = db.Column(db.String(100))
    state = db.Column(db.String(2))
    zip_code = db.Column(db.String(12))
    person_type = db.Column(db.String(20), nullable=False, default='JURIDICA', server_default='JURIDICA')
    state_registration = db.Column(db.String(40))
    state_registration_exempt = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    municipal_registration = db.Column(db.String(40))
    tax_regime = db.Column(db.String(20))
    cnae = db.Column(db.String(20))
    rntrc = db.Column(db.String(30))
    responsible_name = db.Column(db.String(160))
    company_size = db.Column(db.String(30))
    address_number = db.Column(db.String(20))
    neighborhood = db.Column(db.String(100))
    address_complement = db.Column(db.String(100))
    mobile = db.Column(db.String(30))
    website = db.Column(db.String(160))
    weekdays_open = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    weekdays_from = db.Column(db.String(5), nullable=False, default='08:00', server_default='08:00')
    weekdays_to = db.Column(db.String(5), nullable=False, default='18:00', server_default='18:00')
    saturday_open = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    saturday_from = db.Column(db.String(5), nullable=False, default='08:00', server_default='08:00')
    saturday_to = db.Column(db.String(5), nullable=False, default='12:00', server_default='12:00')
    sunday_open = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    sunday_from = db.Column(db.String(5), nullable=False, default='08:00', server_default='08:00')
    sunday_to = db.Column(db.String(5), nullable=False, default='12:00', server_default='12:00')
    accountant_name = db.Column(db.String(160))
    accountant_cpf = db.Column(db.String(20))
    accountant_cnpj = db.Column(db.String(20))
    accountant_crc = db.Column(db.String(40))
    accountant_email = db.Column(db.String(120))
    accountant_phone = db.Column(db.String(30))
    accountant_zip_code = db.Column(db.String(12))
    accountant_address = db.Column(db.String(255))
    accountant_address_number = db.Column(db.String(20))
    accountant_neighborhood = db.Column(db.String(100))
    accountant_complement = db.Column(db.String(100))
    accountant_city = db.Column(db.String(100))
    accountant_state = db.Column(db.String(2))
    certificate_subject = db.Column(db.String(255))
    certificate_serial_number = db.Column(db.String(100))
    certificate_expires_at = db.Column(db.DateTime)
    certificate_synced_at = db.Column(db.DateTime)
    focus_sync_status = db.Column(db.String(20))
    focus_synced_at = db.Column(db.DateTime)
    uninfe_settings_json = db.Column(db.Text)
    budget_prefix = db.Column(db.String(10), nullable=False, default='ORC')
    work_order_prefix = db.Column(db.String(10), nullable=False, default='OS')
    budget_validity_days = db.Column(db.Integer, nullable=False, default=7)
    warranty_days = db.Column(db.Integer, nullable=False, default=90)
    # Assinatura do LS Hub nesta instalação; sem data paga o acesso não é controlado (instalação própria).
    subscription_plan = db.Column(db.String(40))
    subscription_paid_until = db.Column(db.Date)
    subscription_suspended = db.Column(db.Boolean, nullable=False, default=False, server_default='0')

    partners = db.relationship('CompanyPartner', back_populates='settings', cascade='all, delete-orphan', order_by='CompanyPartner.id')


class CompanyPartner(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'company_partners'

    id = db.Column(db.Integer, primary_key=True)
    system_settings_id = db.Column(db.Integer, db.ForeignKey('system_settings.id', ondelete='CASCADE'), nullable=False, index=True)
    full_name = db.Column(db.String(160), nullable=False)
    cpf = db.Column(db.String(20))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    birth_date = db.Column(db.Date)
    rg = db.Column(db.String(30))
    ownership_percentage = db.Column(db.Numeric(5, 2))

    settings = db.relationship('SystemSettings', back_populates='partners')


class Employee(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'employees'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    funcao = db.Column(db.String(80), nullable=False)
    telefone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    observacoes = db.Column(db.Text)

    work_orders = db.relationship('WorkOrder', back_populates='employee')


class Client(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'clients'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), index=True, nullable=False)
    cpf_cnpj = db.Column(db.String(20))
    inscricao_estadual = db.Column(db.String(40))
    telefone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    endereco = db.Column(db.String(255))
    observacoes = db.Column(db.Text)

    budgets = db.relationship('Budget', back_populates='client', cascade='all')
    work_orders = db.relationship('WorkOrder', back_populates='client', cascade='all')


class Service(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'services'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    descricao = db.Column(db.Text)
    preco_base = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    ativo = db.Column(db.Boolean, default=True, nullable=False)


class Product(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(40), unique=True, nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    categoria = db.Column(db.String(80))
    marca = db.Column(db.String(80))
    unidade = db.Column(db.String(20), default='UN', nullable=False)
    ncm = db.Column(db.String(20))
    cfop = db.Column(db.String(10))
    custo = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    preco_venda = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    estoque_atual = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    estoque_minimo = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    stock_reservations = db.relationship('StockReservation', back_populates='product')
    inventory_movements = db.relationship('InventoryMovement', back_populates='product')

class Supplier(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'suppliers'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), nullable=False) # Nome Fantasia ou Nome
    razao_social = db.Column(db.String(160))
    cnpj_cpf = db.Column(db.String(20))
    inscricao_estadual = db.Column(db.String(40))
    telefone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    endereco = db.Column(db.String(255))
    observacoes = db.Column(db.Text)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    stock_entries = db.relationship('StockEntry', back_populates='supplier')


class StockEntry(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'stock_entries'

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    numero_nota = db.Column(db.String(50))
    data_emissao = db.Column(db.Date, nullable=False, default=date.today)
    data_entrada = db.Column(db.Date, nullable=False, default=date.today)
    transportadora = db.Column(db.String(120))
    valor_frete = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    valor_total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    status = db.Column(db.String(30), default='CONCLUIDA', nullable=False)
    observacoes = db.Column(db.Text)

    supplier = db.relationship('Supplier', back_populates='stock_entries')
    items = db.relationship('StockEntryItem', back_populates='stock_entry', cascade='all, delete-orphan', order_by='StockEntryItem.id')


class StockEntryItem(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'stock_entry_items'

    id = db.Column(db.Integer, primary_key=True)
    stock_entry_id = db.Column(db.Integer, db.ForeignKey('stock_entries.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantidade = db.Column(db.Numeric(12, 2), nullable=False, default=1)
    custo_unitario = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total_item = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    stock_entry = db.relationship('StockEntry', back_populates='items')
    product = db.relationship('Product')


class BankAccount(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'bank_accounts'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    banco = db.Column(db.String(120))
    agencia = db.Column(db.String(30))
    conta = db.Column(db.String(40))
    saldo_inicial = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    saldo_atual = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    ativo = db.Column(db.Boolean, default=True, nullable=False)


class XmlInvoiceImport(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'xml_invoice_imports'

    id = db.Column(db.Integer, primary_key=True)
    chave_acesso = db.Column(db.String(60), unique=True, nullable=False)
    numero = db.Column(db.String(30))
    serie = db.Column(db.String(20))
    natureza_operacao = db.Column(db.String(120))
    emitente_nome = db.Column(db.String(160))
    emitente_cnpj = db.Column(db.String(20))
    destinatario_nome = db.Column(db.String(160))
    destinatario_cnpj = db.Column(db.String(20))
    total_nota = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    emissao_em = db.Column(db.Date)
    informacoes_complementares = db.Column(db.Text)
    items_json = db.Column(db.Text, nullable=False, default='[]')
    raw_xml = db.Column(db.Text)

    def set_items(self, items: list[dict]) -> None:
        self.items_json = json.dumps(items, ensure_ascii=False)

    def get_items(self) -> list[dict]:
        try:
            return json.loads(self.items_json or '[]')
        except json.JSONDecodeError:
            return []


class FiscalApiConfig(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'fiscal_api_configs'

    id = db.Column(db.Integer, primary_key=True)
    provider_name = db.Column(db.String(80), nullable=False, default='CUSTOM')
    environment = db.Column(db.String(20), nullable=False, default='HOMOLOGACAO')
    api_base_url = db.Column(db.String(255))
    api_token = db.Column(db.String(255))
    company_name = db.Column(db.String(160))
    company_document = db.Column(db.String(20))
    municipal_registration = db.Column(db.String(40))
    state_registration = db.Column(db.String(40))
    tax_regime = db.Column(db.String(40))
    default_service_code = db.Column(db.String(40))
    default_nature = db.Column(db.String(120))
    webhook_url = db.Column(db.String(255))
    focus_company_id = db.Column(db.String(80))
    focus_management_token = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True, nullable=False)


class FiscalDocument(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'fiscal_documents'

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=True)
    provider_name = db.Column(db.String(80), nullable=False, default='CUSTOM')
    document_type = db.Column(db.String(20), nullable=False, default='NFSE')
    environment = db.Column(db.String(20), nullable=False, default='HOMOLOGACAO')
    status = db.Column(db.String(30), nullable=False, default='RASCUNHO')
    numero = db.Column(db.String(30))
    serie = db.Column(db.String(20))
    external_id = db.Column(db.String(80))
    access_key = db.Column(db.String(80))
    request_payload = db.Column(FISCAL_ARTIFACT_TEXT)
    response_payload = db.Column(FISCAL_ARTIFACT_TEXT)
    xml_content = db.Column(FISCAL_ARTIFACT_TEXT)
    pdf_url = db.Column(db.String(255))
    error_message = db.Column(db.Text)

    work_order = db.relationship('WorkOrder')


class UniNFeSubmission(db.Model, TimestampMixin):
    """Durable invoice identity and immutable content reserved before file I/O."""
    __tablename__ = 'uninfe_submissions'
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('fiscal_documents.id'), nullable=False, unique=True)
    issuer_document = db.Column(db.String(14), nullable=False)
    environment = db.Column(db.String(20), nullable=False)
    model = db.Column(db.String(2), nullable=False)
    series = db.Column(db.Integer, nullable=False)
    number = db.Column(db.Integer, nullable=False)
    access_key = db.Column(db.String(44), nullable=False, unique=True)
    issued_at = db.Column(db.String(32), nullable=False)
    snapshot_json = db.Column(FISCAL_ARTIFACT_TEXT, nullable=False)
    prepared_xml = db.Column(FISCAL_ARTIFACT_TEXT, nullable=False)
    xml_sha256 = db.Column(db.String(64), nullable=False)
    published_at = db.Column(db.DateTime)
    publication_started_at = db.Column(db.DateTime)
    cancellation_xml = db.Column(FISCAL_ARTIFACT_TEXT)
    cancellation_response = db.Column(FISCAL_ARTIFACT_TEXT)
    cancellation_processed_xml = db.Column(FISCAL_ARTIFACT_TEXT)
    __table_args__ = (
        db.UniqueConstraint('issuer_document', 'environment', 'model', 'series', 'number',
                            name='uq_uninfe_fiscal_number'),
    )


class UniNFeRelayTask(db.Model, TimestampMixin):
    """One durable remote delivery permission for each reserved invoice."""
    __tablename__ = 'uninfe_relay_tasks'
    submission_id = db.Column(db.Integer, db.ForeignKey('uninfe_submissions.id'), primary_key=True)
    connector_id = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='WAITING')


class PaymentMethod(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'payment_methods'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), nullable=False, unique=True)
    tipo = db.Column(db.String(30), nullable=False, default='OUTRO')
    permite_parcelamento = db.Column(db.Boolean, default=False, nullable=False)
    parcelas_maximas = db.Column(db.Integer, default=1, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    financial_entries = db.relationship('FinancialEntry', back_populates='payment_method')
    work_orders = db.relationship('WorkOrder', back_populates='payment_method')


class Budget(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'budgets'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), index=True)
    vehicle = db.relationship('Vehicle', back_populates='budgets')
    version = db.Column(db.Integer, default=0, nullable=False, server_default='0')
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    numero = db.Column(db.String(20), unique=True, nullable=False)
    status = db.Column(db.String(30), nullable=False, default='ABERTO')
    placa = db.Column(db.String(10))
    veiculo_descricao = db.Column(db.String(160))
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    desconto = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    observacoes = db.Column(db.Text)
    validade = db.Column(db.Date)

    __mapper_args__ = {'version_id_col': version}

    client = db.relationship('Client', back_populates='budgets')
    items = db.relationship('BudgetItem', back_populates='budget', cascade='all, delete-orphan', order_by='BudgetItem.id')
    work_orders = db.relationship('WorkOrder', back_populates='budget')
    approvals = db.relationship('BudgetApproval', back_populates='budget', cascade='all, delete-orphan', order_by='BudgetApproval.id.desc()')


class BudgetItem(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'budget_items'

    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=False)
    item_type = db.Column(db.String(20), nullable=False)
    reference_id = db.Column(db.Integer)
    descricao = db.Column(db.String(255), nullable=False)
    quantidade = db.Column(db.Numeric(12, 2), nullable=False, default=1)
    valor_unitario = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    desconto = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    classification = db.Column(db.String(20), nullable=False, default='NECESSARIO', server_default='NECESSARIO')

    budget = db.relationship('Budget', back_populates='items')


class WorkOrder(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'work_orders'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), index=True)
    vehicle = db.relationship('Vehicle', back_populates='work_orders')
    version = db.Column(db.Integer, default=0, nullable=False, server_default='0')
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'))
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'))
    payment_method_id = db.Column(db.Integer, db.ForeignKey('payment_methods.id'))
    numero = db.Column(db.String(20), unique=True, nullable=False)
    status = db.Column(db.String(30), index=True, nullable=False, default='ABERTA')
    data_entrada = db.Column(db.Date, index=True, nullable=False, default=date.today)
    data_saida = db.Column(db.Date)
    promised_at = db.Column(db.DateTime, index=True)
    workshop_resource_id = db.Column(db.Integer, db.ForeignKey('workshop_resources.id'), index=True)
    current_stage = db.Column(db.String(30), index=True, nullable=False, default='RECEPCAO')
    blocking_reason = db.Column(db.String(255))
    placa = db.Column(db.String(10))
    veiculo_descricao = db.Column(db.String(160))
    observacoes = db.Column(db.Text)
    installment_count = db.Column(db.Integer, nullable=False, default=1)
    client_nome = db.Column(db.String(160))
    emitir_nota = db.Column(db.Boolean, default=False, nullable=False)
    estoque_baixado = db.Column(db.Boolean, default=False, nullable=False)
    total_pecas = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total_servicos = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total_geral = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    desconto = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default='0')
    tipo_atendimento = db.Column(db.String(20))  # INTERNO / EXTERNO / GARANTIA
    problema_relatado = db.Column(db.Text)
    laudo = db.Column(db.Text)
    observacoes_cliente = db.Column(db.Text)

    __mapper_args__ = {'version_id_col': version}

    client = db.relationship('Client', back_populates='work_orders')
    employee = db.relationship('Employee', back_populates='work_orders')
    budget = db.relationship('Budget', back_populates='work_orders')
    payment_method = db.relationship('PaymentMethod', back_populates='work_orders')
    items = db.relationship('WorkOrderItem', back_populates='work_order', cascade='all, delete-orphan', order_by='WorkOrderItem.id')
    checklist = db.relationship('WorkOrderChecklist', back_populates='work_order', uselist=False, cascade='all, delete-orphan')
    status_history = db.relationship('WorkOrderStatusHistory', back_populates='work_order', cascade='all, delete-orphan', order_by='WorkOrderStatusHistory.changed_at.desc()')
    payments = db.relationship('WorkOrderPayment', back_populates='work_order', cascade='all, delete-orphan', order_by='WorkOrderPayment.id')
    workshop_resource = db.relationship('WorkshopResource')
    stage_history = db.relationship('WorkOrderStageHistory', back_populates='work_order', cascade='all, delete-orphan', order_by='WorkOrderStageHistory.started_at.desc()')
    inspection = db.relationship('VehicleInspection', back_populates='work_order', uselist=False, cascade='all, delete-orphan')
    stock_reservations = db.relationship('StockReservation', back_populates='work_order', cascade='all, delete-orphan')
    inventory_movements = db.relationship('InventoryMovement', back_populates='work_order')
    warranty = db.relationship('ServiceWarranty', back_populates='work_order', uselist=False, cascade='all, delete-orphan')


class WorkOrderStatusHistory(db.Model, SerializableMixin):
    __tablename__ = 'work_order_status_history'

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    status = db.Column(db.String(30), nullable=False)
    observation = db.Column(db.Text)
    changed_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    work_order = db.relationship('WorkOrder', back_populates='status_history')
    user = db.relationship('User')


class WorkOrderItem(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'work_order_items'

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False)
    item_type = db.Column(db.String(20), nullable=False)
    reference_id = db.Column(db.Integer)
    descricao = db.Column(db.String(255), nullable=False)
    quantidade = db.Column(db.Numeric(12, 2), nullable=False, default=1)
    valor_unitario = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    desconto = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    work_order = db.relationship('WorkOrder', back_populates='items')
    stock_reservation = db.relationship('StockReservation', back_populates='work_order_item', uselist=False, cascade='all, delete-orphan')


class WorkOrderChecklist(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'work_order_checklists'

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), unique=True, nullable=False)
    lataria_ok = db.Column(db.Boolean, default=False, nullable=False)
    pneus_ok = db.Column(db.Boolean, default=False, nullable=False)
    estepe = db.Column(db.Boolean, default=False, nullable=False)
    chave_roda_macaco = db.Column(db.Boolean, default=False, nullable=False)
    documentos_ok = db.Column(db.Boolean, default=False, nullable=False)
    som_multimidia = db.Column(db.Boolean, default=False, nullable=False)
    combustivel = db.Column(db.String(20), default='1/2')
    observacoes = db.Column(db.Text)

    work_order = db.relationship('WorkOrder', back_populates='checklist')


class FinancialEntry(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'financial_entries'

    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.Integer, default=0, nullable=False, server_default='0')
    entry_type = db.Column(db.String(20), index=True, nullable=False)
    descricao = db.Column(db.String(255), nullable=False)
    categoria = db.Column(db.String(80))
    valor = db.Column(db.Numeric(12, 2), nullable=False)
    vencimento = db.Column(db.Date, index=True, nullable=False)
    payment_receipt_at = db.Column(db.Date)
    status = db.Column(db.String(20), index=True, nullable=False, default='PENDENTE')
    payment_method_id = db.Column(db.Integer, db.ForeignKey('payment_methods.id'))
    installment_number = db.Column(db.Integer, nullable=False, default=1)
    installment_total = db.Column(db.Integer, nullable=False, default=1)
    reference_type = db.Column(db.String(30))
    reference_id = db.Column(db.Integer)
    bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'))
    issued_on = db.Column(db.Date, nullable=False, default=date.today)
    competence_on = db.Column(db.Date, nullable=False, default=date.today, index=True)
    chart_account_id = db.Column(db.Integer, db.ForeignKey('chart_of_accounts.id'), index=True)
    cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id'), index=True)

    # Campos de liquidação (baixa) detalhada
    valor_baixa = db.Column(db.Numeric(12, 2))
    juros = db.Column(db.Numeric(12, 2), default=0, server_default='0')
    desconto = db.Column(db.Numeric(12, 2), default=0, server_default='0')
    taxa = db.Column(db.Numeric(12, 2), default=0, server_default='0')
    acrescimo = db.Column(db.Numeric(12, 2), default=0, server_default='0')
    observacoes_pagamento = db.Column(db.Text)

    __mapper_args__ = {'version_id_col': version}

    bank_account = db.relationship('BankAccount')

    payment_method = db.relationship('PaymentMethod', back_populates='financial_entries')
    chart_account = db.relationship('ChartOfAccount')
    cost_center = db.relationship('CostCenter')


PURCHASE_REFERENCES = {'XML_NFE', 'ENTRADA_ESTOQUE'}


def default_category(entry_type: str, reference_type: str | None) -> str:
    """Categoria usada quando o lançamento chega sem uma (O.S., notas, importações e scripts)."""
    if reference_type == 'OS':
        return 'Ordens de Serviço'
    if reference_type in PURCHASE_REFERENCES:
        return 'Compra de peças'
    return 'Outras receitas' if entry_type == 'RECEBER' else 'Outras despesas'


@event.listens_for(FinancialEntry, 'before_insert')
def _fill_category(_mapper, _connection, entry: FinancialEntry) -> None:
    if not (entry.categoria or '').strip():
        entry.categoria = default_category(entry.entry_type, entry.reference_type)


class ChartOfAccount(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'chart_of_accounts'
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('chart_of_accounts.id'))
    code = db.Column(db.String(30), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    parent = db.relationship('ChartOfAccount', remote_side=[id])


class CostCenter(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'cost_centers'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)


class BankTransaction(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'bank_transactions'
    id = db.Column(db.Integer, primary_key=True)
    bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=False, index=True)
    external_id = db.Column(db.String(120))
    posted_on = db.Column(db.Date, nullable=False, index=True)
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    source = db.Column(db.String(20), nullable=False, default='CSV')
    bank_account = db.relationship('BankAccount')
    __table_args__ = (db.UniqueConstraint('bank_account_id', 'external_id', name='uq_bank_transaction_external'),)


class BankReconciliation(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'bank_reconciliations'
    id = db.Column(db.Integer, primary_key=True)
    bank_transaction_id = db.Column(db.Integer, db.ForeignKey('bank_transactions.id'), nullable=False, unique=True)
    financial_entry_id = db.Column(db.Integer, db.ForeignKey('financial_entries.id'), nullable=False, unique=True)
    reconciled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    bank_transaction = db.relationship('BankTransaction')
    financial_entry = db.relationship('FinancialEntry')


class CommissionRule(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'commission_rules'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    applies_to = db.Column(db.String(20), nullable=False, default='SERVICO')
    calculation_type = db.Column(db.String(20), nullable=False, default='PERCENTUAL')
    value = db.Column(db.Numeric(12, 4), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)


class CommissionEntry(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'commission_entries'
    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer, db.ForeignKey('commission_rules.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='PROVISIONADA')
    rule = db.relationship('CommissionRule')
    employee = db.relationship('Employee')
    work_order = db.relationship('WorkOrder')


class StockLocation(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'stock_locations'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)


class PurchaseRequest(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'purchase_requests'
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(30), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default='ABERTA', index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'))
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    notes = db.Column(db.Text)
    supplier = db.relationship('Supplier')
    items = db.relationship('PurchaseRequestItem', back_populates='purchase_request', cascade='all, delete-orphan')


class PurchaseRequestItem(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'purchase_request_items'
    id = db.Column(db.Integer, primary_key=True)
    purchase_request_id = db.Column(db.Integer, db.ForeignKey('purchase_requests.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Numeric(12, 2), nullable=False)
    quoted_unit_cost = db.Column(db.Numeric(12, 2))
    received_quantity = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    purchase_request = db.relationship('PurchaseRequest', back_populates='items')
    product = db.relationship('Product')


class InventoryCount(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'inventory_counts'
    id = db.Column(db.Integer, primary_key=True)
    stock_location_id = db.Column(db.Integer, db.ForeignKey('stock_locations.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='ABERTO')
    counted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    closed_at = db.Column(db.DateTime)
    location = db.relationship('StockLocation')
    items = db.relationship('InventoryCountItem', back_populates='inventory_count', cascade='all, delete-orphan')


class InventoryCountItem(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'inventory_count_items'
    id = db.Column(db.Integer, primary_key=True)
    inventory_count_id = db.Column(db.Integer, db.ForeignKey('inventory_counts.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    expected_quantity = db.Column(db.Numeric(12, 2), nullable=False)
    counted_quantity = db.Column(db.Numeric(12, 2))
    inventory_count = db.relationship('InventoryCount', back_populates='items')
    product = db.relationship('Product')


class AssistantState(db.Model, TimestampMixin):
    """Conversa e propostas do assistente no servidor: o cookie de sessão não comporta nem protege esses dados."""
    __tablename__ = 'assistant_states'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    history_json = db.Column(db.Text, nullable=False, default='[]')
    drafts_json = db.Column(db.Text, nullable=False, default='{}')


class AsyncJob(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'async_jobs'
    id = db.Column(db.Integer, primary_key=True)
    job_type = db.Column(db.String(40), nullable=False, index=True)
    payload_json = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='PENDENTE', index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    available_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
    last_error = db.Column(db.Text)


class WorkOrderPayment(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'work_order_payments'

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False)
    payment_method_id = db.Column(db.Integer, db.ForeignKey('payment_methods.id'), nullable=False)
    valor = db.Column(db.Numeric(12, 2), nullable=False)
    installment_count = db.Column(db.Integer, nullable=False, default=1)

    work_order = db.relationship('WorkOrder', back_populates='payments')
    payment_method = db.relationship('PaymentMethod')

