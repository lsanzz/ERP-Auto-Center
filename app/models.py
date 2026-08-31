from __future__ import annotations

from datetime import date, datetime
import json
from decimal import Decimal

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()


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

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)


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
    budget_prefix = db.Column(db.String(10), nullable=False, default='ORC')
    work_order_prefix = db.Column(db.String(10), nullable=False, default='OS')
    budget_validity_days = db.Column(db.Integer, nullable=False, default=7)
    warranty_days = db.Column(db.Integer, nullable=False, default=90)


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
    request_payload = db.Column(db.Text)
    response_payload = db.Column(db.Text)
    xml_content = db.Column(db.Text)
    pdf_url = db.Column(db.String(255))
    error_message = db.Column(db.Text)

    work_order = db.relationship('WorkOrder')


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

    budget = db.relationship('Budget', back_populates='items')


class WorkOrder(db.Model, TimestampMixin, SerializableMixin):
    __tablename__ = 'work_orders'

    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.Integer, default=0, nullable=False, server_default='0')
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'))
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'))
    payment_method_id = db.Column(db.Integer, db.ForeignKey('payment_methods.id'))
    numero = db.Column(db.String(20), unique=True, nullable=False)
    status = db.Column(db.String(30), index=True, nullable=False, default='ABERTA')
    data_entrada = db.Column(db.Date, index=True, nullable=False, default=date.today)
    data_saida = db.Column(db.Date)
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

    __mapper_args__ = {'version_id_col': version}

    client = db.relationship('Client', back_populates='work_orders')
    employee = db.relationship('Employee', back_populates='work_orders')
    budget = db.relationship('Budget', back_populates='work_orders')
    payment_method = db.relationship('PaymentMethod', back_populates='work_orders')
    items = db.relationship('WorkOrderItem', back_populates='work_order', cascade='all, delete-orphan', order_by='WorkOrderItem.id')
    checklist = db.relationship('WorkOrderChecklist', back_populates='work_order', uselist=False, cascade='all, delete-orphan')
    status_history = db.relationship('WorkOrderStatusHistory', back_populates='work_order', cascade='all, delete-orphan', order_by='WorkOrderStatusHistory.changed_at.desc()')


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

    __mapper_args__ = {'version_id_col': version}

    bank_account = db.relationship('BankAccount')

    payment_method = db.relationship('PaymentMethod', back_populates='financial_entries')
