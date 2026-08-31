from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import func, or_
from sqlalchemy.exc import OperationalError

from .models import (
    BankAccount,
    Budget,
    BudgetItem,
    FinancialEntry,
    Product,
    Service,
    WorkOrder,
    WorkOrderChecklist,
    WorkOrderItem,
    WorkOrderStatusHistory,
    db,
)
from .utils import parse_date, parse_decimal
from .settings import get_system_settings


BUDGET_STATUSES = ['ABERTO', 'APROVADO', 'REPROVADO', 'CANCELADO']
WORK_ORDER_STATUSES = ['ABERTA', 'EM_ANDAMENTO', 'AGUARDANDO_PECA', 'FINALIZADA', 'ENTREGUE', 'CANCELADA']
FUEL_OPTIONS = ['NA_RESERVA', '1/4', '1/2', '3/4', 'CHEIO']
CHECKLIST_FIELDS = ['lataria_ok', 'pneus_ok', 'estepe', 'chave_roda_macaco', 'documentos_ok', 'som_multimidia']


def next_number(model, prefix: str, field: str = 'numero') -> str:
    last = model.query.order_by(model.id.desc()).first()
    if not last:
        return f'{prefix}-00001'
    last_value = getattr(last, field, '') or ''
    try:
        number = int(last_value.split('-')[-1]) + 1
    except ValueError:
        number = last.id + 1
    return f'{prefix}-{number:05d}'


def recalculate_budget_totals(budget: Budget) -> Budget:
    subtotal = Decimal('0')
    for item in budget.items:
        subtotal += parse_decimal(item.total)
    budget.subtotal = subtotal
    budget.total = subtotal - parse_decimal(budget.desconto)
    if budget.total < 0:
        budget.total = Decimal('0')
    return budget


def recalculate_work_order_totals(order: WorkOrder) -> WorkOrder:
    total_pecas = Decimal('0')
    total_servicos = Decimal('0')
    for item in order.items:
        if item.item_type == 'PECA':
            total_pecas += parse_decimal(item.total)
        else:
            total_servicos += parse_decimal(item.total)
    order.total_pecas = total_pecas
    order.total_servicos = total_servicos
    order.total_geral = total_pecas + total_servicos
    if order.total_geral < 0:
        order.total_geral = Decimal('0')
    return order


def _resolve_catalog_item(item_type: str, reference_id: int) -> tuple[str, Decimal]:
    if item_type == 'SERVICO':
        entity = db.session.get(Service, reference_id)
        if not entity:
            raise ValueError('Serviço não encontrado.')
        return entity.nome, parse_decimal(entity.preco_base)
    if item_type == 'PECA':
        entity = db.session.get(Product, reference_id)
        if not entity:
            raise ValueError('Peça não encontrada.')
        return entity.nome, parse_decimal(entity.preco_venda)
    raise ValueError('Tipo de item inválido.')


def _resolve_catalog_item_by_description(item_type: str, descricao: str | None) -> tuple[int | None, str | None, Decimal | None]:
    descricao = (descricao or '').strip()
    if not descricao:
        return None, None, None
    if item_type == 'SERVICO':
        entity = Service.query.filter(func.lower(Service.nome) == descricao.lower(), Service.ativo.is_(True)).first()
        if entity:
            return entity.id, entity.nome, parse_decimal(entity.preco_base)
    elif item_type == 'PECA':
        entity = Product.query.filter(func.lower(Product.nome) == descricao.lower(), Product.ativo.is_(True)).first()
        if entity:
            return entity.id, entity.nome, parse_decimal(entity.preco_venda)
    return None, None, None


def _build_item_values(
    item_type: str,
    reference_id: int | None,
    quantidade,
    desconto=0,
    descricao: str | None = None,
    valor_unitario=None,
    total=None,
) -> tuple[int | None, str, Decimal, Decimal, Decimal, Decimal]:
    if item_type not in {'SERVICO', 'PECA'}:
        raise ValueError('Tipo de item inválido.')
    normalized_reference = int(reference_id) if reference_id not in (None, '') else None
    quantidade_value = parse_decimal(quantidade, 1)
    if quantidade_value <= 0:
        raise ValueError('A quantidade do item deve ser maior que zero.')
    catalog_description = None
    catalog_unit_value = None
    if normalized_reference is not None:
        catalog_description, catalog_unit_value = _resolve_catalog_item(item_type, normalized_reference)
    descricao_value = (descricao or catalog_description or '').strip().upper()
    if not descricao_value:
        label = 'serviço' if item_type == 'SERVICO' else 'peça'
        raise ValueError(f'Informe o nome da {label}.')
    if normalized_reference is None:
        normalized_reference, matched_description, matched_unit_value = _resolve_catalog_item_by_description(item_type, descricao_value)
        if matched_description:
            catalog_description = matched_description
            descricao_value = matched_description
            catalog_unit_value = matched_unit_value
    unit_value = parse_decimal(valor_unitario, catalog_unit_value or Decimal('0'))
    if unit_value < 0:
        raise ValueError('O preço unitário não pode ser negativo.')
    discount_value = parse_decimal(desconto)
    if discount_value < 0:
        discount_value = Decimal('0')
    if total in (None, ''):
        total_value = (quantidade_value * unit_value) - discount_value
    else:
        total_value = parse_decimal(total)
        if total_value < 0:
            raise ValueError('O preço final não pode ser negativo.')
        computed_total = quantidade_value * unit_value
        if discount_value == 0 and computed_total >= total_value:
            discount_value = computed_total - total_value
    if total_value < 0:
        total_value = Decimal('0')
    return normalized_reference, descricao_value, quantidade_value, unit_value, discount_value, total_value


def add_budget_item(budget, item_type, reference_id=None, quantidade=1, desconto=0, descricao=None, valor_unitario=None, total=None) -> BudgetItem:
    reference_id, descricao, quantidade, valor_unitario, desconto, total = _build_item_values(item_type=item_type, reference_id=reference_id, quantidade=quantidade, desconto=desconto, descricao=descricao, valor_unitario=valor_unitario, total=total)
    item = BudgetItem(budget=budget, item_type=item_type, reference_id=reference_id, descricao=descricao, quantidade=quantidade, valor_unitario=valor_unitario, desconto=desconto, total=total)
    db.session.add(item)
    db.session.flush()
    recalculate_budget_totals(budget)
    return item


def add_work_order_item(order, item_type, reference_id=None, quantidade=1, desconto=0, descricao=None, valor_unitario=None, total=None) -> WorkOrderItem:
    reference_id, descricao, quantidade, valor_unitario, desconto, total = _build_item_values(item_type=item_type, reference_id=reference_id, quantidade=quantidade, desconto=desconto, descricao=descricao, valor_unitario=valor_unitario, total=total)
    item = WorkOrderItem(work_order=order, item_type=item_type, reference_id=reference_id, descricao=descricao, quantidade=quantidade, valor_unitario=valor_unitario, desconto=desconto, total=total)
    db.session.add(item)
    db.session.flush()
    recalculate_work_order_totals(order)
    return item


def replace_work_order_items(order: WorkOrder, items_payload: list[dict]) -> list[WorkOrderItem]:
    for item in list(order.items):
        order.items.remove(item)
    db.session.flush()
    created_items: list[WorkOrderItem] = []
    for payload in items_payload:
        created_items.append(add_work_order_item(order, item_type=payload.get('item_type', ''), reference_id=payload.get('reference_id'), quantidade=payload.get('quantidade'), desconto=payload.get('desconto', 0), descricao=payload.get('descricao'), valor_unitario=payload.get('valor_unitario'), total=payload.get('total')))
    recalculate_work_order_totals(order)
    return created_items


def approve_budget(budget: Budget) -> Budget:
    budget.status = 'APROVADO'
    recalculate_budget_totals(budget)
    return budget


def create_work_order_from_budget(budget: Budget) -> WorkOrder:
    if budget.status != 'APROVADO':
        raise ValueError('Somente orçamentos aprovados podem ser convertidos em OS.')
    if budget.work_orders:
        raise ValueError('Este orçamento já foi convertido em ordem de serviço.')
    order = WorkOrder(client_id=budget.client_id, client_nome=budget.client.nome if budget.client else None, budget=budget, numero=next_number(WorkOrder, get_system_settings().work_order_prefix or 'OS'), status='ABERTA', data_entrada=date.today(), placa=budget.placa, veiculo_descricao=budget.veiculo_descricao, observacoes=budget.observacoes, installment_count=1)
    db.session.add(order)
    db.session.flush()
    for item in budget.items:
        add_work_order_item(order, item_type=item.item_type, reference_id=item.reference_id, quantidade=item.quantidade, desconto=item.desconto, descricao=item.descricao, valor_unitario=item.valor_unitario, total=item.total)
    ensure_work_order_checklist(order)
    recalculate_work_order_totals(order)
    return order


def ensure_work_order_checklist(order: WorkOrder) -> WorkOrderChecklist:
    if order.checklist:
        return order.checklist
    checklist = WorkOrderChecklist(work_order=order)
    db.session.add(checklist)
    db.session.flush()
    return checklist


def update_work_order_checklist(order: WorkOrder, data: dict) -> WorkOrderChecklist:
    checklist = ensure_work_order_checklist(order)
    for field in CHECKLIST_FIELDS:
        setattr(checklist, field, bool(data.get(field)))
    if data.get('combustivel'):
        checklist.combustivel = data.get('combustivel')
    checklist.observacoes = data.get('observacoes')
    return checklist


def change_work_order_status(order: WorkOrder, status: str) -> WorkOrder:
    if status not in WORK_ORDER_STATUSES:
        raise ValueError('Status de OS inválido.')
    order.status = status
    if status in {'FINALIZADA', 'ENTREGUE'} and not order.data_saida:
        order.data_saida = date.today()
    return order


def record_work_order_status(order: WorkOrder, status: str, user_id: int | None = None, observation: str | None = None) -> WorkOrderStatusHistory:
    history = WorkOrderStatusHistory(work_order=order, status=status, user_id=user_id, observation=(observation or '').strip() or None)
    db.session.add(history)
    return history


def add_months(base_date: date, months: int) -> date:
    month_index = base_date.month - 1 + months
    year = base_date.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def split_installments(total, installment_count: int) -> list[Decimal]:
    total = parse_decimal(total).quantize(Decimal('0.01'))
    installment_count = max(int(installment_count or 1), 1)
    if installment_count == 1:
        return [total]
    base_value = (total / installment_count).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    values = [base_value for _ in range(installment_count)]
    remainder = (total - (base_value * installment_count)).quantize(Decimal('0.01'))
    remainder_cents = int((remainder * 100).quantize(Decimal('1')))
    for index in range(remainder_cents):
        values[index] += Decimal('0.01')
    return values


def ensure_work_order_receivables(order: WorkOrder) -> list[FinancialEntry]:
    recalculate_work_order_totals(order)
    existing = (FinancialEntry.query.filter_by(reference_type='OS', reference_id=order.id).order_by(FinancialEntry.installment_number.asc(), FinancialEntry.id.asc()).all())
    if existing:
        return existing
        
    entries: list[FinancialEntry] = []
    
    if getattr(order, 'payments', None) and len(order.payments) > 0:
        for payment_idx, payment in enumerate(order.payments):
            installments = int(payment.installment_count or 1)
            method = payment.payment_method
            if not method or not method.permite_parcelamento:
                installments = 1
                
            installment_values = split_installments(payment.valor, installments)
            for number, value in enumerate(installment_values, start=1):
                description = f'Recebimento referente a {order.numero} ({method.nome})'
                if installments > 1:
                    description += f' ({number}/{installments})'
                entry = FinancialEntry(
                    entry_type='RECEBER', 
                    descricao=description, 
                    categoria='Ordens de Serviço', 
                    valor=value, 
                    vencimento=add_months(date.today(), number - 1), 
                    status='PENDENTE', 
                    payment_method_id=payment.payment_method_id, 
                    installment_number=number, 
                    installment_total=installments, 
                    reference_type='OS', 
                    reference_id=order.id
                )
                db.session.add(entry)
                entries.append(entry)
    else:
        installments = int(order.installment_count or 1)
        payment_method = order.payment_method
        if not payment_method or not payment_method.permite_parcelamento:
            installments = 1
            order.installment_count = 1
            
        installment_values = split_installments(order.total_geral, installments)
        for number, value in enumerate(installment_values, start=1):
            description = f'Recebimento referente a {order.numero}'
            if installments > 1:
                description += f' ({number}/{installments})'
            entry = FinancialEntry(
                entry_type='RECEBER', 
                descricao=description, 
                categoria='Ordens de Serviço', 
                valor=value, 
                vencimento=add_months(date.today(), number - 1), 
                status='PENDENTE', 
                payment_method_id=order.payment_method_id, 
                installment_number=number, 
                installment_total=installments, 
                reference_type='OS', 
                reference_id=order.id
            )
            db.session.add(entry)
            entries.append(entry)
            
    db.session.flush()
    return entries


def _is_postgres() -> bool:
    """Retorna True se o banco de dados atual eh PostgreSQL."""
    return db.session.bind is not None and db.session.bind.dialect.name == 'postgresql'


def finalize_work_order(order: WorkOrder) -> list[FinancialEntry]:
    """Finaliza a OS com lock exclusivo para evitar dupla finalizacao."""
    if _is_postgres():
        locked = db.session.query(WorkOrder).filter_by(id=order.id).with_for_update().first()
    else:
        locked = db.session.get(WorkOrder, order.id)
    if locked is None:
        raise ValueError('Ordem de serviço não encontrada.')
    if locked.status in {'FINALIZADA', 'ENTREGUE'}:
        return FinancialEntry.query.filter_by(reference_type='OS', reference_id=locked.id).all()
    locked.status = 'FINALIZADA'
    locked.data_saida = date.today()
    order.status = locked.status
    order.data_saida = locked.data_saida
    return ensure_work_order_receivables(locked)


def deduct_work_order_stock(order: WorkOrder) -> list[str]:
    """Baixa estoque das pecas. Usa SELECT FOR UPDATE para evitar baixa dupla."""
    if _is_postgres():
        locked_order = db.session.query(WorkOrder).filter_by(id=order.id).with_for_update().first()
    else:
        locked_order = db.session.get(WorkOrder, order.id)
    if locked_order is None or locked_order.estoque_baixado:
        return []
    warnings = []
    for item in locked_order.items:
        if item.item_type != 'PECA' or not item.reference_id:
            continue
        if _is_postgres():
            product = db.session.query(Product).filter_by(id=item.reference_id).with_for_update().first()
        else:
            product = db.session.get(Product, item.reference_id)
        if not product:
            continue
        quantity = parse_decimal(item.quantidade)
        product.estoque_atual = parse_decimal(product.estoque_atual) - quantity
        if product.estoque_atual < parse_decimal(product.estoque_minimo):
            warnings.append(f'{product.nome}: estoque abaixo do mínimo')
    locked_order.estoque_baixado = True
    order.estoque_baixado = True
    return warnings


def settle_financial_entry(entry: FinancialEntry, payment_method_id: int | None = None, payment_receipt_at=None, bank_account_id: int | None = None) -> FinancialEntry:
    """Liquida lancamento e atualiza saldo bancario. Usa FOR UPDATE para evitar race condition."""
    entry.payment_receipt_at = parse_date(payment_receipt_at) or date.today()
    if payment_method_id:
        entry.payment_method_id = payment_method_id
    if bank_account_id:
        entry.bank_account_id = bank_account_id
    entry.status = 'RECEBIDO' if entry.entry_type == 'RECEBER' else 'PAGO'
    if entry.bank_account_id:
        if _is_postgres():
            account = db.session.query(BankAccount).filter_by(id=entry.bank_account_id).with_for_update().first()
        else:
            account = db.session.get(BankAccount, entry.bank_account_id)
        if account:
            value = parse_decimal(entry.valor)
            if entry.entry_type == 'RECEBER':
                account.saldo_atual = parse_decimal(account.saldo_atual) + value
            else:
                account.saldo_atual = parse_decimal(account.saldo_atual) - value
    return entry


def update_work_order_receivables(order: WorkOrder, status: str, payment_method_id: int | None = None, payment_receipt_at=None, bank_account_id: int | None = None) -> list[FinancialEntry]:
    entries = (FinancialEntry.query.filter_by(reference_type='OS', reference_id=order.id).order_by(FinancialEntry.installment_number.asc(), FinancialEntry.id.asc()).all())
    if not entries:
        raise ValueError('Nenhuma conta a receber foi lançada para esta O.S..')
    normalized = (status or 'PENDENTE').upper()
    if normalized not in {'PENDENTE', 'RECEBIDO'}:
        raise ValueError('Status de recebimento inválido.')
    for entry in entries:
        if normalized == 'RECEBIDO':
            if entry.status == 'RECEBIDO':
                if payment_method_id:
                    entry.payment_method_id = payment_method_id
                if bank_account_id is not None:
                    entry.bank_account_id = bank_account_id or None
                entry.payment_receipt_at = parse_date(payment_receipt_at) or entry.payment_receipt_at or date.today()
            else:
                settle_financial_entry(entry, payment_method_id=payment_method_id, payment_receipt_at=payment_receipt_at, bank_account_id=bank_account_id)
        else:
            if entry.status == 'RECEBIDO' and entry.bank_account_id:
                if _is_postgres():
                    account = db.session.query(BankAccount).filter_by(id=entry.bank_account_id).with_for_update().first()
                else:
                    account = db.session.get(BankAccount, entry.bank_account_id)
                if account:
                    account.saldo_atual = parse_decimal(account.saldo_atual) - parse_decimal(entry.valor)
            entry.status = 'PENDENTE'
            entry.payment_receipt_at = None
            if payment_method_id:
                entry.payment_method_id = payment_method_id
            if bank_account_id is not None:
                entry.bank_account_id = bank_account_id or None
    return entries


def client_history(client_id: int) -> dict:
    return {
        'budgets': Budget.query.filter_by(client_id=client_id).order_by(Budget.id.desc()).all(),
        'work_orders': WorkOrder.query.filter_by(client_id=client_id).order_by(WorkOrder.id.desc()).all(),
    }


def services_rank(limit: int = 5):
    return (
        db.session.query(WorkOrderItem.descricao.label('descricao'), func.sum(WorkOrderItem.quantidade).label('quantidade'))
        .filter(WorkOrderItem.item_type == 'SERVICO')
        .group_by(WorkOrderItem.descricao)
        .order_by(func.sum(WorkOrderItem.quantidade).desc())
        .limit(limit)
        .all()
    )


def daily_cash_summary() -> dict:
    today = date.today()
    recebidos = Decimal('0')
    pagos = Decimal('0')
    entries = FinancialEntry.query.filter(FinancialEntry.payment_receipt_at == today).all()
    for entry in entries:
        if entry.entry_type == 'RECEBER' and entry.status == 'RECEBIDO':
            recebidos += parse_decimal(entry.valor)
        if entry.entry_type == 'PAGAR' and entry.status == 'PAGO':
            pagos += parse_decimal(entry.valor)
    return {'recebidos': recebidos, 'pagos': pagos, 'saldo': recebidos - pagos}


def create_financial_entries(entry_type, descricao, categoria, valor_total, vencimento, status='PENDENTE', payment_method_id=None, bank_account_id=None, reference_type=None, reference_id=None, installment_count=1, payment_receipt_at=None) -> list[FinancialEntry]:
    due_date = parse_date(vencimento) or date.today()
    installment_count = max(int(installment_count or 1), 1)
    values = split_installments(valor_total, installment_count)
    entries: list[FinancialEntry] = []
    normalized_status = status or 'PENDENTE'
    for number, value in enumerate(values, start=1):
        label = descricao
        if installment_count > 1:
            label = f'{descricao} ({number}/{installment_count})'
        entry = FinancialEntry(entry_type=entry_type, descricao=label, categoria=categoria, valor=value, vencimento=add_months(due_date, number - 1), status=normalized_status, payment_method_id=payment_method_id, bank_account_id=bank_account_id, installment_number=number, installment_total=installment_count, reference_type=reference_type, reference_id=reference_id)
        db.session.add(entry)
        entries.append(entry)
    db.session.flush()
    if normalized_status in {'RECEBIDO', 'PAGO'}:
        for entry in entries:
            settle_financial_entry(entry, payment_method_id=payment_method_id, payment_receipt_at=payment_receipt_at or entry.vencimento, bank_account_id=bank_account_id)
    return entries



def dashboard_data(user_role: str = 'ADMINISTRADOR') -> dict:
    closed_statuses = ['FINALIZADA', 'ENTREGUE', 'CANCELADA']
    os_abertas = WorkOrder.query.filter(~WorkOrder.status.in_(closed_statuses), WorkOrder.data_entrada == date.today()).count()
    os_andamento = WorkOrder.query.filter(WorkOrder.status == 'EM_ANDAMENTO', WorkOrder.data_entrada == date.today()).count()
    faturamento_dia = Decimal('0')
    if user_role == 'ADMINISTRADOR':
        entries = FinancialEntry.query.filter(FinancialEntry.entry_type == 'RECEBER', FinancialEntry.status == 'RECEBIDO', FinancialEntry.payment_receipt_at == date.today()).all()
        for entry in entries:
            faturamento_dia += parse_decimal(entry.valor)
    bank_accounts = []
    bank_accounts_total = None
    if user_role == 'ADMINISTRADOR':
        bank_accounts = BankAccount.query.filter_by(ativo=True).order_by(BankAccount.nome).all()
        bank_accounts_total = sum(parse_decimal(account.saldo_atual) for account in bank_accounts)
    return {
        'os_abertas': os_abertas,
        'os_andamento': os_andamento,
        'faturamento_dia': faturamento_dia if user_role == 'ADMINISTRADOR' else None,
        'caixa_diario': daily_cash_summary() if user_role == 'ADMINISTRADOR' else None,
        'bank_accounts': bank_accounts if user_role == 'ADMINISTRADOR' else [],
        'bank_accounts_total': bank_accounts_total if user_role == 'ADMINISTRADOR' else None,
        'services_rank': services_rank(),
    }

def daily_cash_summary() -> dict:
    today = date.today()
    recebidos = Decimal('0')
    pagos = Decimal('0')
    entries = FinancialEntry.query.filter(FinancialEntry.payment_receipt_at == today).all()
    for entry in entries:
        if entry.entry_type == 'RECEBER' and entry.status == 'RECEBIDO':
            recebidos += parse_decimal(entry.valor)
        if entry.entry_type == 'PAGAR' and entry.status == 'PAGO':
            pagos += parse_decimal(entry.valor)
    return {'recebidos': recebidos, 'pagos': pagos, 'saldo': recebidos - pagos}

def services_rank() -> list[dict]:
    from sqlalchemy import func
    from .models import WorkOrderItem, db
    
    # Check if WorkOrderItem has 'item_type', if not we just rank all items
    # Wait, the previous snippet had: WorkOrderItem.item_type == 'SERVICO'
    results = (
        db.session.query(
            WorkOrderItem.descricao,
            func.sum(WorkOrderItem.quantidade).label('quantidade'),
        )
        .filter(WorkOrderItem.item_type == 'SERVICO')
        .group_by(WorkOrderItem.descricao)
        .order_by(func.sum(WorkOrderItem.quantidade).desc())
        .limit(5)
        .all()
    )
    return [{'descricao': row[0], 'quantidade': float(row[1])} for row in results]

def client_history(client_id: int) -> dict:
    from .models import WorkOrder
    return {
        'work_orders': WorkOrder.query.filter_by(client_id=client_id).order_by(WorkOrder.id.desc()).all()
    }
