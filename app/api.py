from __future__ import annotations

from datetime import date
from functools import wraps

from flask import Blueprint, jsonify, request

from .auth import current_user, login_user, logout_user
from .cnpj import is_cnpj, is_cpf, lookup_cnpj, lookup_cpf
from .models import BankAccount, Budget, Client, Employee, FinancialEntry, PaymentMethod, Product, Service, User, WorkOrder, XmlInvoiceImport, db
from .services import (
    BUDGET_STATUSES,
    WORK_ORDER_STATUSES,
    add_budget_item,
    add_work_order_item,
    approve_budget,
    create_financial_entries,
    change_work_order_status,
    create_work_order_from_budget,
    dashboard_data,
    finalize_work_order,
    next_number,
    recalculate_budget_totals,
    recalculate_work_order_totals,
    replace_work_order_items,
    settle_financial_entry,
    split_installments,
)
from .utils import parse_date, parse_decimal
from .xml_import import parse_nfe_xml


api_bp = Blueprint('api', __name__)


def as_json(data, status: int = 200):
    return jsonify(data), status


def payload() -> dict:
    return request.get_json(silent=True) or {}


def api_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return as_json({'error': 'não autenticado'}, 401)
        return view(*args, **kwargs)

    return wrapped


def api_roles_required(*roles: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return as_json({'error': 'não autenticado'}, 401)
            if user.role not in roles:
                return as_json({'error': 'acesso negado'}, 403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def get_or_404(model, entity_id):
    return db.session.get(model, entity_id)


def normalize_installment_count(payment_method_id, installment_count) -> int:
    if not payment_method_id:
        return 1
    method = db.session.get(PaymentMethod, int(payment_method_id))
    if not method or not method.permite_parcelamento:
        return 1
    max_installments = max(method.parcelas_maximas or 1, 1)
    return min(max(int(installment_count or 1), 1), max_installments)


def serialize_budget(budget: Budget) -> dict:
    data = budget.to_dict()
    data['client'] = budget.client.to_dict() if budget.client else None
    data['items'] = [item.to_dict() for item in budget.items]
    return data


def serialize_work_order(order: WorkOrder) -> dict:
    data = order.to_dict()
    data['client'] = order.client.to_dict() if order.client else None
    data['client_nome'] = order.client_nome or (order.client.nome if order.client else None)
    data['nome_cliente'] = order.client_nome or (order.client.nome if order.client else None)
    data['employee'] = order.employee.to_dict() if order.employee else None
    data['payment_method'] = order.payment_method.to_dict() if order.payment_method else None
    data['installment_values'] = [float(value) for value in split_installments(order.total_geral, order.installment_count or 1)] if order.payment_method and order.payment_method.permite_parcelamento else []
    data['items'] = [item.to_dict() for item in order.items]
    data['servicos'] = [item.to_dict() for item in order.items if item.item_type == 'SERVICO']
    data['pecas'] = [item.to_dict() for item in order.items if item.item_type == 'PECA']
    if current_user() and current_user().role == 'ADMINISTRADOR':
        data['financial_entries'] = [
            entry.to_dict()
            for entry in FinancialEntry.query.filter_by(reference_type='OS', reference_id=order.id).order_by(FinancialEntry.installment_number.asc(), FinancialEntry.id.asc()).all()
        ]
    return data


def _save_client_from_payload(client: Client, data: dict) -> None:
    document = data.get('cpf_cnpj')
    autofill = bool(data.get('autofill_document') or data.get('autofill_cnpj'))
    lookup_data = None
    if autofill and is_cnpj(document):
        lookup_data = lookup_cnpj(document)
    elif autofill and is_cpf(document):
        lookup_data = lookup_cpf(document)

    client.nome = data.get('nome') or (lookup_data or {}).get('nome') or client.nome
    client.cpf_cnpj = document if document is not None else client.cpf_cnpj
    client.telefone = data.get('telefone') or (lookup_data or {}).get('telefone') or client.telefone
    client.email = data.get('email') or (lookup_data or {}).get('email') or client.email
    client.endereco = data.get('endereco') or (lookup_data or {}).get('endereco') or client.endereco
    client.observacoes = data.get('observacoes', client.observacoes)


def _resolve_item_payload(data: dict) -> tuple[str, int]:
    item_type = (data.get('item_type') or '').upper()
    if item_type == 'SERVICO':
        reference_id = data.get('service_id') or data.get('reference_id')
        normalized_type = 'SERVICO'
    elif item_type in {'PRODUTO', 'PECA'}:
        reference_id = data.get('product_id') or data.get('part_id') or data.get('reference_id')
        normalized_type = 'PECA'
    else:
        raise ValueError('Tipo de item inválido.')
    if not reference_id:
        raise ValueError('Selecione um item do catálogo.')
    return normalized_type, int(reference_id)


def _normalize_work_order_item_payload(item: dict, default_type: str | None = None) -> dict:
    if not isinstance(item, dict):
        raise ValueError('Cada item da O.S. deve ser um objeto.')

    inferred_type = default_type
    if not inferred_type and (item.get('service_id') or item.get('item_type') == 'SERVICO'):
        inferred_type = 'SERVICO'
    if not inferred_type and (item.get('product_id') or item.get('part_id') or str(item.get('item_type') or '').upper() in {'PRODUTO', 'PECA'}):
        inferred_type = 'PECA'

    item_type = (item.get('item_type') or inferred_type or '').upper()
    if item_type == 'PRODUTO':
        item_type = 'PECA'
    if item_type not in {'SERVICO', 'PECA'}:
        raise ValueError('Tipo de item inválido.')

    reference_id = item.get('reference_id')
    if item_type == 'SERVICO':
        reference_id = reference_id or item.get('service_id')
    if item_type == 'PECA':
        reference_id = reference_id or item.get('product_id') or item.get('part_id')

    return {
        'item_type': item_type,
        'reference_id': int(reference_id) if reference_id not in (None, '') else None,
        'descricao': item.get('descricao') or item.get('nome') or item.get('name'),
        'quantidade': item.get('quantidade'),
        'valor_unitario': item.get('valor_unitario', item.get('preco_unitario')),
        'total': item.get('total', item.get('preco_final')),
        'desconto': item.get('desconto', 0),
    }




def _resolve_or_create_client_from_payload(data: dict) -> Client:
    selected_id = data.get('client_id')
    typed_name = (data.get('client_nome') or data.get('nome_cliente') or '').strip()
    if selected_id:
        client = db.session.get(Client, int(selected_id))
        if not client:
            raise ValueError('Cliente selecionado não encontrado.')
        return client
    if not typed_name:
        raise ValueError('Informe o nome do cliente ou selecione um cadastro existente.')
    existing = Client.query.filter(db.func.lower(Client.nome) == typed_name.lower()).first()
    if existing:
        return existing
    client = Client(nome=typed_name)
    db.session.add(client)
    db.session.flush()
    return client


def _collect_work_order_item_payloads(data: dict) -> list[dict]:
    items: list[dict] = []
    for raw_item in data.get('items') or []:
        items.append(_normalize_work_order_item_payload(raw_item))
    for raw_item in data.get('servicos') or []:
        items.append(_normalize_work_order_item_payload(raw_item, 'SERVICO'))
    for raw_item in data.get('pecas') or []:
        items.append(_normalize_work_order_item_payload(raw_item, 'PECA'))
    return items


@api_bp.get('/health')
def health():
    return as_json({'status': 'ok', 'service': 'erp-auto-center'})


@api_bp.post('/session')
def session_create():
    data = payload()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    user = User.query.filter_by(username=username, ativo=True).first()
    if not user or not user.check_password(password):
        return as_json({'error': 'credenciais inválidas'}, 401)
    login_user(user)
    return as_json({'message': 'autenticado', 'user': {'id': user.id, 'username': user.username, 'role': user.role}})


@api_bp.delete('/session')
@api_login_required
def session_delete():
    logout_user()
    return as_json({'message': 'sessão encerrada'})


@api_bp.get('/dashboard')
@api_login_required
def dashboard():
    data = dashboard_data(current_user().role)
    if current_user().role == 'ADMINISTRADOR':
        data['bank_accounts'] = [account.to_dict() for account in data.get('bank_accounts', [])]
    return as_json(data)


@api_bp.get('/clientes/documento/<string:document>')
@api_login_required
def client_lookup_document(document: str):
    try:
        if is_cpf(document):
            return as_json(lookup_cpf(document))
        if is_cnpj(document):
            return as_json(lookup_cnpj(document))
        return as_json({'error': 'Informe um CPF ou CNPJ válido.'}, 400)
    except ValueError as exc:
        return as_json({'error': str(exc)}, 400)
    except LookupError as exc:
        return as_json({'error': str(exc)}, 404)
    except RuntimeError as exc:
        return as_json({'error': str(exc)}, 503)


@api_bp.get('/clientes/cnpj/<string:document>')
@api_login_required
def client_lookup_cnpj(document: str):
    try:
        return as_json(lookup_cnpj(document))
    except ValueError as exc:
        return as_json({'error': str(exc)}, 400)
    except LookupError as exc:
        return as_json({'error': str(exc)}, 404)
    except RuntimeError as exc:
        return as_json({'error': str(exc)}, 503)


@api_bp.route('/clientes', methods=['GET', 'POST'])
@api_login_required
def clients_collection():
    if request.method == 'GET':
        return as_json([client.to_dict() for client in Client.query.order_by(Client.nome).all()])

    client = Client()
    _save_client_from_payload(client, payload())
    db.session.add(client)
    db.session.commit()
    return as_json(client.to_dict(), 201)


@api_bp.route('/clientes/<int:client_id>', methods=['GET', 'PATCH'])
@api_login_required
def client_resource(client_id: int):
    client = get_or_404(Client, client_id)
    if not client:
        return as_json({'error': 'cliente não encontrado'}, 404)
    if request.method == 'GET':
        data = client.to_dict()
        data['budgets'] = [serialize_budget(budget) for budget in client.budgets]
        data['work_orders'] = [serialize_work_order(order) for order in client.work_orders]
        return as_json(data)

    _save_client_from_payload(client, payload())
    db.session.commit()
    return as_json(client.to_dict())


@api_bp.route('/produtos', methods=['GET', 'POST'])
@api_login_required
def products_collection():
    if request.method == 'GET':
        return as_json([product.to_dict() for product in Product.query.order_by(Product.nome).all()])
    if current_user().role != 'ADMINISTRADOR':
        return as_json({'error': 'acesso negado'}, 403)
    data = payload()
    product = Product(
        codigo=data.get('codigo', '').strip(),
        nome=data.get('nome', '').strip(),
        categoria=data.get('categoria') or None,
        marca=data.get('marca') or None,
        unidade=data.get('unidade') or 'UN',
        custo=parse_decimal(data.get('custo')),
        preco_venda=parse_decimal(data.get('preco_venda')),
        ativo=bool(data.get('ativo', True)),
    )
    db.session.add(product)
    db.session.commit()
    return as_json(product.to_dict(), 201)


@api_bp.route('/produtos/<int:product_id>', methods=['GET', 'PATCH'])
@api_login_required
def product_resource(product_id: int):
    product = get_or_404(Product, product_id)
    if not product:
        return as_json({'error': 'peça não encontrada'}, 404)
    if request.method == 'GET':
        return as_json(product.to_dict())
    if current_user().role != 'ADMINISTRADOR':
        return as_json({'error': 'acesso negado'}, 403)
    data = payload()
    for field in ['codigo', 'nome', 'categoria', 'marca', 'unidade']:
        if field in data:
            setattr(product, field, data.get(field) or None)
    if 'custo' in data:
        product.custo = parse_decimal(data.get('custo'))
    if 'preco_venda' in data:
        product.preco_venda = parse_decimal(data.get('preco_venda'))
    if 'ativo' in data:
        product.ativo = bool(data.get('ativo'))
    db.session.commit()
    return as_json(product.to_dict())


@api_bp.route('/servicos', methods=['GET', 'POST'])
@api_login_required
def services_collection():
    if request.method == 'GET':
        return as_json([service.to_dict() for service in Service.query.order_by(Service.nome).all()])
    if current_user().role != 'ADMINISTRADOR':
        return as_json({'error': 'acesso negado'}, 403)
    data = payload()
    service = Service(
        nome=data.get('nome', '').strip(),
        descricao=data.get('descricao') or None,
        preco_base=parse_decimal(data.get('preco_base')),
        ativo=bool(data.get('ativo', True)),
    )
    db.session.add(service)
    db.session.commit()
    return as_json(service.to_dict(), 201)


@api_bp.route('/servicos/<int:service_id>', methods=['GET', 'PATCH'])
@api_login_required
def service_resource(service_id: int):
    service = get_or_404(Service, service_id)
    if not service:
        return as_json({'error': 'serviço não encontrado'}, 404)
    if request.method == 'GET':
        return as_json(service.to_dict())
    if current_user().role != 'ADMINISTRADOR':
        return as_json({'error': 'acesso negado'}, 403)
    data = payload()
    for field in ['nome', 'descricao']:
        if field in data:
            setattr(service, field, data.get(field) or None)
    if 'preco_base' in data:
        service.preco_base = parse_decimal(data.get('preco_base'))
    if 'ativo' in data:
        service.ativo = bool(data.get('ativo'))
    db.session.commit()
    return as_json(service.to_dict())


@api_bp.route('/orcamentos', methods=['GET', 'POST'])
@api_login_required
def budgets_collection():
    if request.method == 'GET':
        return as_json([serialize_budget(budget) for budget in Budget.query.order_by(Budget.id.desc()).all()])
    data = payload()
    budget = Budget(
        client_id=int(data.get('client_id')),
        numero=next_number(Budget, 'ORC'),
        status=data.get('status') or 'ABERTO',
        placa=(data.get('placa') or '').upper() or None,
        veiculo_descricao=data.get('veiculo_descricao') or None,
        desconto=parse_decimal(data.get('desconto')),
        observacoes=data.get('observacoes') or None,
        validade=parse_date(data.get('validade')),
    )
    db.session.add(budget)
    db.session.flush()
    recalculate_budget_totals(budget)
    db.session.commit()
    return as_json(serialize_budget(budget), 201)


@api_bp.route('/orcamentos/<int:budget_id>', methods=['GET', 'PATCH'])
@api_login_required
def budget_resource(budget_id: int):
    budget = get_or_404(Budget, budget_id)
    if not budget:
        return as_json({'error': 'orçamento não encontrado'}, 404)
    if request.method == 'GET':
        return as_json(serialize_budget(budget))
    data = payload()
    for field in ['placa', 'veiculo_descricao', 'observacoes']:
        if field in data:
            value = data.get(field)
            setattr(budget, field, value.upper() if field == 'placa' and value else value)
    if 'client_id' in data:
        budget.client_id = int(data.get('client_id'))
    if 'status' in data and data.get('status') in BUDGET_STATUSES:
        budget.status = data.get('status')
    if 'desconto' in data:
        budget.desconto = parse_decimal(data.get('desconto'))
    if 'validade' in data:
        budget.validade = parse_date(data.get('validade'))
    recalculate_budget_totals(budget)
    db.session.commit()
    return as_json(serialize_budget(budget))


@api_bp.post('/orcamentos/<int:budget_id>/itens')
@api_login_required
def budget_add_item(budget_id: int):
    budget = get_or_404(Budget, budget_id)
    if not budget:
        return as_json({'error': 'orçamento não encontrado'}, 404)
    try:
        item_type, reference_id = _resolve_item_payload(payload())
        item = add_budget_item(budget, item_type=item_type, reference_id=reference_id, quantidade=payload().get('quantidade'), desconto=payload().get('desconto'))
        db.session.commit()
        return as_json(item.to_dict(), 201)
    except ValueError as exc:
        db.session.rollback()
        return as_json({'error': str(exc)}, 400)


@api_bp.post('/orcamentos/<int:budget_id>/aprovar')
@api_login_required
def budget_approve(budget_id: int):
    budget = get_or_404(Budget, budget_id)
    if not budget:
        return as_json({'error': 'orçamento não encontrado'}, 404)
    approve_budget(budget)
    db.session.commit()
    return as_json(serialize_budget(budget))


@api_bp.post('/orcamentos/<int:budget_id>/converter-os')
@api_login_required
def budget_convert(budget_id: int):
    budget = get_or_404(Budget, budget_id)
    if not budget:
        return as_json({'error': 'orçamento não encontrado'}, 404)
    try:
        order = create_work_order_from_budget(budget)
        db.session.commit()
        return as_json(serialize_work_order(order), 201)
    except ValueError as exc:
        db.session.rollback()
        return as_json({'error': str(exc)}, 400)


@api_bp.route('/os', methods=['GET', 'POST'])
@api_login_required
def work_orders_collection():
    if request.method == 'GET':
        return as_json([serialize_work_order(order) for order in WorkOrder.query.order_by(WorkOrder.id.desc()).all()])

    data = payload()
    try:
        items_payload = _collect_work_order_item_payloads(data)
        client = _resolve_or_create_client_from_payload(data)
        order = WorkOrder(
            client_id=client.id,
            client_nome=(data.get('client_nome') or data.get('nome_cliente') or client.nome),
            employee_id=int(data.get('employee_id')) if data.get('employee_id') else None,
            budget_id=int(data.get('budget_id')) if data.get('budget_id') else None,
            payment_method_id=int(data.get('payment_method_id')) if data.get('payment_method_id') else None,
            numero=next_number(WorkOrder, 'OS'),
            status=data.get('status') or 'ABERTA',
            data_entrada=parse_date(data.get('data_entrada')) or date.today(),
            placa=(data.get('placa') or '').upper() or None,
            veiculo_descricao=data.get('veiculo_descricao') or None,
            observacoes=data.get('observacoes') or None,
            installment_count=normalize_installment_count(data.get('payment_method_id'), data.get('installment_count')),
            emitir_nota=True,
        )
        db.session.add(order)
        db.session.flush()
        if items_payload:
            replace_work_order_items(order, items_payload)
        else:
            recalculate_work_order_totals(order)
        db.session.commit()
        return as_json(serialize_work_order(order), 201)
    except ValueError as exc:
        db.session.rollback()
        return as_json({'error': str(exc)}, 400)


@api_bp.route('/os/<int:work_order_id>', methods=['GET', 'PATCH'])
@api_login_required
def work_order_resource(work_order_id: int):
    order = get_or_404(WorkOrder, work_order_id)
    if not order:
        return as_json({'error': 'ordem de serviço não encontrada'}, 404)
    if request.method == 'GET':
        return as_json(serialize_work_order(order))

    data = payload()
    try:
        items_payload = None
        if any(key in data for key in ['items', 'servicos', 'pecas']):
            items_payload = _collect_work_order_item_payloads(data)

        for field in ['placa', 'veiculo_descricao', 'observacoes']:
            if field in data:
                value = data.get(field)
                setattr(order, field, value.upper() if field == 'placa' and value else value)
        if 'client_id' in data or 'client_nome' in data or 'nome_cliente' in data:
            client = _resolve_or_create_client_from_payload({'client_id': data.get('client_id', order.client_id), 'client_nome': data.get('client_nome') or data.get('nome_cliente') or order.client_nome})
            order.client_id = client.id
            order.client_nome = data.get('client_nome') or data.get('nome_cliente') or client.nome
        if 'employee_id' in data:
            order.employee_id = int(data.get('employee_id')) if data.get('employee_id') else None
        if 'budget_id' in data:
            order.budget_id = int(data.get('budget_id')) if data.get('budget_id') else None
        if 'payment_method_id' in data:
            order.payment_method_id = int(data.get('payment_method_id')) if data.get('payment_method_id') else None
        if 'installment_count' in data or 'payment_method_id' in data:
            order.installment_count = normalize_installment_count(order.payment_method_id, data.get('installment_count', order.installment_count))
        if 'status' in data and data.get('status') in WORK_ORDER_STATUSES:
            order.status = data.get('status')
        if 'data_entrada' in data:
            order.data_entrada = parse_date(data.get('data_entrada'))
        if 'emitir_nota' in data:
            order.emitir_nota = True

        if items_payload is not None:
            replace_work_order_items(order, items_payload)
        else:
            recalculate_work_order_totals(order)
        db.session.commit()
        return as_json(serialize_work_order(order))
    except ValueError as exc:
        db.session.rollback()
        return as_json({'error': str(exc)}, 400)


@api_bp.post('/os/<int:work_order_id>/itens')
@api_login_required
def work_order_add_item(work_order_id: int):
    order = get_or_404(WorkOrder, work_order_id)
    if not order:
        return as_json({'error': 'ordem de serviço não encontrada'}, 404)
    data = payload()
    try:
        item_payload = _normalize_work_order_item_payload(data)
        item = add_work_order_item(
            order,
            item_type=item_payload['item_type'],
            reference_id=item_payload.get('reference_id'),
            quantidade=item_payload.get('quantidade'),
            desconto=item_payload.get('desconto'),
            descricao=item_payload.get('descricao'),
            valor_unitario=item_payload.get('valor_unitario'),
            total=item_payload.get('total'),
        )
        db.session.commit()
        return as_json(item.to_dict(), 201)
    except ValueError as exc:
        db.session.rollback()
        return as_json({'error': str(exc)}, 400)


@api_bp.post('/os/<int:work_order_id>/status')
@api_login_required
def work_order_change_status(work_order_id: int):
    order = get_or_404(WorkOrder, work_order_id)
    if not order:
        return as_json({'error': 'ordem de serviço não encontrada'}, 404)
    try:
        change_work_order_status(order, payload().get('status', ''))
        db.session.commit()
        return as_json(serialize_work_order(order))
    except ValueError as exc:
        db.session.rollback()
        return as_json({'error': str(exc)}, 400)



@api_bp.post('/os/<int:work_order_id>/finalizar')
@api_login_required
def work_order_finish(work_order_id: int):
    order = get_or_404(WorkOrder, work_order_id)
    if not order:
        return as_json({'error': 'ordem de serviço não encontrada'}, 404)
    entries = finalize_work_order(order)
    db.session.commit()
    return as_json({'work_order': serialize_work_order(order), 'financial_entries': [entry.to_dict() for entry in entries]})


@api_bp.route('/financeiro', methods=['GET', 'POST'])
@api_roles_required('ADMINISTRADOR')
def finance_collection():
    if request.method == 'GET':
        entries = FinancialEntry.query.order_by(FinancialEntry.vencimento.desc(), FinancialEntry.id.desc()).all()
        return as_json({'caixa_diario': dashboard_data('ADMINISTRADOR')['caixa_diario'], 'items': [entry.to_dict() for entry in entries]})
    data = payload()
    entry_type = data.get('entry_type') or 'RECEBER'
    payment_mode = data.get('payment_mode') or ('PARCELADO' if int(data.get('installment_count') or 1) > 1 else 'UNICO')
    installment_count = int(data.get('installment_count') or 1)
    valor_total = parse_decimal(data.get('valor'))
    if entry_type == 'PAGAR' and payment_mode == 'PARCELADO':
        valor_total = parse_decimal(data.get('installment_value')) * max(installment_count, 1)
    else:
        installment_count = 1
    entries = create_financial_entries(
        entry_type=entry_type,
        descricao=data.get('descricao', '').strip(),
        categoria=data.get('categoria') or None,
        valor_total=valor_total,
        vencimento=data.get('vencimento'),
        status=data.get('status') or 'PENDENTE',
        payment_method_id=int(data.get('payment_method_id')) if data.get('payment_method_id') else None,
        bank_account_id=int(data.get('bank_account_id')) if data.get('bank_account_id') else None,
        reference_type=data.get('reference_type') or None,
        reference_id=int(data.get('reference_id')) if data.get('reference_id') else None,
        installment_count=installment_count,
        payment_receipt_at=data.get('payment_receipt_at'),
    )
    db.session.commit()
    return as_json([entry.to_dict() for entry in entries] if len(entries) > 1 else entries[0].to_dict(), 201)


@api_bp.post('/financeiro/<int:entry_id>/liquidar')
@api_bp.post('/financeiro/<int:entry_id>/quitar')
@api_roles_required('ADMINISTRADOR')
def finance_settle(entry_id: int):
    entry = get_or_404(FinancialEntry, entry_id)
    if not entry:
        return as_json({'error': 'lançamento não encontrado'}, 404)
    data = payload()
    settle_financial_entry(entry, payment_method_id=int(data.get('payment_method_id')) if data.get('payment_method_id') else None, payment_receipt_at=data.get('payment_receipt_at'), bank_account_id=int(data.get('bank_account_id')) if data.get('bank_account_id') else None)
    db.session.commit()
    return as_json(entry.to_dict())


@api_bp.route('/contas-bancarias', methods=['GET', 'POST'])
@api_roles_required('ADMINISTRADOR')
def bank_accounts_collection():
    if request.method == 'GET':
        return as_json([account.to_dict() for account in BankAccount.query.order_by(BankAccount.nome).all()])
    data = payload()
    account = BankAccount(
        nome=data.get('nome', '').strip(),
        banco=data.get('banco') or None,
        agencia=data.get('agencia') or None,
        conta=data.get('conta') or None,
        saldo_inicial=parse_decimal(data.get('saldo_inicial')),
        saldo_atual=parse_decimal(data.get('saldo_atual', data.get('saldo_inicial'))),
        ativo=bool(data.get('ativo', True)),
    )
    db.session.add(account)
    db.session.commit()
    return as_json(account.to_dict(), 201)


@api_bp.route('/contas-bancarias/<int:account_id>', methods=['GET', 'PATCH', 'DELETE'])
@api_roles_required('ADMINISTRADOR')
def bank_account_resource(account_id: int):
    account = get_or_404(BankAccount, account_id)
    if not account:
        return as_json({'error': 'conta bancária não encontrada'}, 404)
    if request.method == 'GET':
        return as_json(account.to_dict())
    if request.method == 'DELETE':
        db.session.delete(account)
        db.session.commit()
        return as_json({'message': 'conta bancária removida'})
    data = payload()
    for field in ['nome', 'banco', 'agencia', 'conta']:
        if field in data:
            setattr(account, field, data.get(field) or None)
    if 'saldo_inicial' in data:
        account.saldo_inicial = parse_decimal(data.get('saldo_inicial'))
    if 'saldo_atual' in data:
        account.saldo_atual = parse_decimal(data.get('saldo_atual'))
    if 'ativo' in data:
        account.ativo = bool(data.get('ativo'))
    db.session.commit()
    return as_json(account.to_dict())


@api_bp.post('/financeiro/importar-xml')
@api_roles_required('ADMINISTRADOR')
def finance_import_xml():
    upload = request.files.get('xml_file')
    if not upload:
        return as_json({'error': 'arquivo xml obrigatório'}, 400)
    try:
        parsed = parse_nfe_xml(upload.read())
        if XmlInvoiceImport.query.filter_by(chave_acesso=parsed['chave_acesso']).first():
            return as_json({'error': 'xml já importado'}, 409)
        xml_import = XmlInvoiceImport(
            chave_acesso=parsed['chave_acesso'],
            numero=parsed.get('numero'),
            serie=parsed.get('serie'),
            natureza_operacao=parsed.get('natureza_operacao'),
            emitente_nome=parsed.get('emitente_nome'),
            emitente_cnpj=parsed.get('emitente_cnpj'),
            destinatario_nome=parsed.get('destinatario_nome'),
            destinatario_cnpj=parsed.get('destinatario_cnpj'),
            total_nota=parse_decimal(parsed.get('total_nota')),
            emissao_em=parse_date(parsed.get('issued_at')),
            informacoes_complementares=parsed.get('informacoes_complementares'),
        )
        xml_import.set_items(parsed.get('itens') or [])
        db.session.add(xml_import)
        db.session.flush()
        entries = create_financial_entries(
            entry_type='PAGAR',
            descricao=f"NF-e {parsed.get('numero')} - {parsed.get('emitente_nome')}",
            categoria='NF-e XML',
            valor_total=parse_decimal(parsed.get('total_nota')),
            vencimento=parsed.get('issued_at'),
            status='PENDENTE',
            reference_type='XML_NFE',
            reference_id=xml_import.id,
            installment_count=int(request.form.get('installment_count') or 1),
        )
        db.session.commit()
        return as_json({'xml': xml_import.to_dict() | {'items': xml_import.get_items()}, 'financial_entries': [entry.to_dict() for entry in entries]}, 201)
    except Exception as exc:
        db.session.rollback()
        return as_json({'error': str(exc)}, 400)


@api_bp.route('/formas-pagamento', methods=['GET', 'POST'])
@api_roles_required('ADMINISTRADOR')
def payment_methods_collection():
    if request.method == 'GET':
        return as_json([method.to_dict() for method in PaymentMethod.query.order_by(PaymentMethod.nome).all()])
    data = payload()
    payment_type = data.get('tipo') or 'OUTRO'
    method = PaymentMethod(
        nome=data.get('nome', '').strip(),
        tipo=payment_type,
        permite_parcelamento=bool(data.get('permite_parcelamento', False)) if payment_type == 'CREDITO' else False,
        parcelas_maximas=int(data.get('parcelas_maximas') or 1) if payment_type == 'CREDITO' else 1,
        ativo=bool(data.get('ativo', True)),
    )
    db.session.add(method)
    db.session.commit()
    return as_json(method.to_dict(), 201)


@api_bp.route('/formas-pagamento/<int:method_id>', methods=['GET', 'PATCH'])
@api_roles_required('ADMINISTRADOR')
def payment_method_resource(method_id: int):
    method = get_or_404(PaymentMethod, method_id)
    if not method:
        return as_json({'error': 'forma de pagamento não encontrada'}, 404)
    if request.method == 'GET':
        return as_json(method.to_dict())
    data = payload()
    if 'nome' in data:
        method.nome = data.get('nome', '').strip()
    if 'tipo' in data:
        method.tipo = data.get('tipo') or 'OUTRO'
    if 'ativo' in data:
        method.ativo = bool(data.get('ativo'))
    if method.tipo == 'CREDITO':
        if 'permite_parcelamento' in data:
            method.permite_parcelamento = bool(data.get('permite_parcelamento'))
        if 'parcelas_maximas' in data:
            method.parcelas_maximas = int(data.get('parcelas_maximas') or 1)
    else:
        method.permite_parcelamento = False
        method.parcelas_maximas = 1
    db.session.commit()
    return as_json(method.to_dict())


@api_bp.route('/funcionarios', methods=['GET', 'POST'])
@api_roles_required('ADMINISTRADOR')
def employees_collection():
    if request.method == 'GET':
        return as_json([employee.to_dict() for employee in Employee.query.order_by(Employee.nome).all()])
    data = payload()
    employee = Employee(
        nome=data.get('nome', '').strip(),
        funcao=data.get('funcao', '').strip(),
        telefone=data.get('telefone') or None,
        email=data.get('email') or None,
        observacoes=data.get('observacoes') or None,
        ativo=bool(data.get('ativo', True)),
    )
    db.session.add(employee)
    db.session.commit()
    return as_json(employee.to_dict(), 201)


@api_bp.route('/funcionarios/<int:employee_id>', methods=['GET', 'PATCH'])
@api_roles_required('ADMINISTRADOR')
def employee_resource(employee_id: int):
    employee = get_or_404(Employee, employee_id)
    if not employee:
        return as_json({'error': 'funcionário não encontrado'}, 404)
    if request.method == 'GET':
        return as_json(employee.to_dict())
    data = payload()
    for field in ['nome', 'funcao', 'telefone', 'email', 'observacoes']:
        if field in data:
            setattr(employee, field, data.get(field) or None)
    if 'ativo' in data:
        employee.ativo = bool(data.get('ativo'))
    db.session.commit()
    return as_json(employee.to_dict())
