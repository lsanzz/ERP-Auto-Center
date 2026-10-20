from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func

from ..models import Budget, Product, StockEntry, StockEntryItem, Supplier, WorkOrder, db
from ..settings import get_system_settings
from ..utils import parse_decimal
from .models import (
    AuditEvent,
    BudgetApproval,
    BudgetApprovalItem,
    BudgetRevision,
    InspectionItem,
    InventoryMovement,
    ServiceWarranty,
    StockReservation,
    VehicleInspection,
)


INSPECTION_CONDITIONS = ['OK', 'ATENCAO', 'CRITICO', 'NAO_VERIFICADO']
DEFAULT_INSPECTION_ITEMS = [
    ('Seguranca', 'Freios'), ('Seguranca', 'Pneus'), ('Seguranca', 'Suspensao'),
    ('Motor', 'Nivel e aspecto do oleo'), ('Motor', 'Sistema de arrefecimento'),
    ('Eletrica', 'Bateria e alternador'), ('Eletrica', 'Iluminacao e sinalizacao'),
    ('Exterior', 'Lataria, vidros e retrovisores'), ('Interior', 'Painel e itens pessoais'),
]


def ensure_inspection(order: WorkOrder) -> VehicleInspection:
    if order.inspection:
        return order.inspection
    inspection = VehicleInspection(work_order=order)
    db.session.add(inspection)
    for area, description in DEFAULT_INSPECTION_ITEMS:
        inspection.items.append(InspectionItem(area=area, description=description))
    db.session.flush()
    return inspection


def update_inspection(inspection: VehicleInspection, form, user_id: int | None = None) -> VehicleInspection:
    odometer = (form.get('odometer') or '').strip()
    inspection.odometer = int(odometer) if odometer else None
    if inspection.odometer is not None and inspection.odometer < 0:
        raise ValueError('A quilometragem nao pode ser negativa.')
    inspection.notes = (form.get('notes') or '').strip() or None
    for item in inspection.items:
        condition = (form.get(f'condition_{item.id}') or 'NAO_VERIFICADO').upper()
        if condition not in INSPECTION_CONDITIONS:
            raise ValueError('Condicao de inspecao invalida.')
        item.condition = condition
        item.notes = (form.get(f'notes_{item.id}') or '').strip() or None
    if form.get('complete') == '1':
        if any(item.condition == 'NAO_VERIFICADO' for item in inspection.items):
            raise ValueError('Verifique todos os itens antes de concluir a inspecao.')
        inspection.status = 'CONCLUIDA'
        inspection.completed_at = datetime.now()
        inspection.completed_by_id = user_id
    else:
        inspection.status = 'RASCUNHO'
        inspection.completed_at = None
        inspection.completed_by_id = None
    return inspection


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


def create_budget_approval(budget: Budget, user_id: int | None = None, valid_days: int = 7):
    for approval in budget.approvals:
        if approval.status == 'PENDENTE':
            approval.status = 'REVOGADO'
    latest_number = db.session.query(func.coalesce(func.max(BudgetRevision.revision_number), 0)).filter(
        BudgetRevision.budget_id == budget.id).scalar()
    snapshot = {
        'budget_id': budget.id, 'number': budget.numero, 'client': budget.client.nome,
        'vehicle': budget.veiculo_descricao, 'plate': budget.placa,
        'subtotal': str(budget.subtotal), 'discount': str(budget.desconto), 'total': str(budget.total),
        'items': [item.to_dict() for item in budget.items],
    }
    revision = BudgetRevision(
        budget_id=budget.id, revision_number=int(latest_number) + 1,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
        total=budget.total, created_by_id=user_id,
    )
    db.session.add(revision)
    db.session.flush()
    raw_token = secrets.token_urlsafe(32)
    approval = BudgetApproval(
        budget=budget,
        token_hash=_token_hash(raw_token),
        expires_at=datetime.now() + timedelta(days=max(valid_days, 1)),
        created_by_id=user_id,
        revision=revision,
    )
    db.session.add(approval)
    db.session.flush()
    for item in budget.items:
        approval.item_decisions.append(BudgetApprovalItem(
            budget_item_id=item.id, description_snapshot=item.descricao,
            total_snapshot=item.total, decision='PENDENTE',
        ))
    db.session.flush()
    return approval, raw_token


def find_budget_approval(raw_token: str) -> BudgetApproval | None:
    if not raw_token:
        return None
    return BudgetApproval.query.filter_by(token_hash=_token_hash(raw_token)).first()


def respond_to_budget_approval(approval: BudgetApproval, decision: str, form, ip: str | None, user_agent: str | None):
    if approval.status != 'PENDENTE':
        raise ValueError('Este link ja foi utilizado ou revogado.')
    if approval.expires_at < datetime.now():
        approval.status = 'EXPIRADO'
        raise ValueError('Este link de aprovacao expirou.')
    decision = (decision or '').upper()
    if decision not in {'APROVADO', 'REPROVADO'}:
        raise ValueError('Resposta invalida.')
    name = (form.get('name') or '').strip()
    if len(name) < 3 or form.get('confirmation') != '1':
        raise ValueError('Informe seu nome e confirme a decisao.')
    selected = []
    for item in approval.item_decisions:
        item_decision = (form.get(f'item_{item.budget_item_id}') or '').upper() or decision
        if item_decision not in {'APROVADO', 'REPROVADO', 'ADIADO'}:
            raise ValueError('Revise a decisao de todos os itens.')
        item.decision = item_decision
        if item_decision == 'APROVADO':
            selected.append(item)
    if not approval.item_decisions:
        approval.status = decision
        approval.approved_total = parse_decimal(approval.revision.total if approval.revision else approval.budget.total) if decision == 'APROVADO' else Decimal('0')
    elif selected and len(selected) < len(approval.item_decisions):
        approval.status = 'APROVADO_PARCIAL'
    elif selected:
        approval.status = 'APROVADO'
    else:
        approval.status = 'REPROVADO'
    if approval.item_decisions:
        approval.approved_total = sum((parse_decimal(item.total_snapshot) for item in selected), Decimal('0'))
    approval.responded_at = datetime.now()
    approval.response_name = name
    approval.response_document = (form.get('document') or '').strip()[:30] or None
    approval.response_note = (form.get('note') or '').strip() or None
    approval.response_ip = (ip or '')[:64] or None
    approval.response_user_agent = (user_agent or '')[:255] or None
    approval.budget.status = approval.status
    return approval


def _lock_product(product_id: int) -> Product | None:
    query = Product.query.filter_by(id=product_id)
    if db.session.get_bind().dialect.name == 'mysql':
        query = query.with_for_update()
    return query.first()


def active_reserved_quantity(product_id: int, excluding_order_id: int | None = None) -> Decimal:
    query = db.session.query(func.coalesce(func.sum(StockReservation.quantity), 0)).filter(
        StockReservation.product_id == product_id, StockReservation.status == 'ATIVA')
    if excluding_order_id:
        query = query.filter(StockReservation.work_order_id != excluding_order_id)
    return parse_decimal(query.scalar())


def reserve_order_parts(order: WorkOrder) -> list[StockReservation]:
    reservations = []
    part_items = [item for item in order.items if item.item_type == 'PECA' and item.reference_id]
    for item in part_items:
        product = _lock_product(item.reference_id)
        if not product:
            raise ValueError(f'Produto do item {item.descricao} nao foi encontrado.')
        needed = parse_decimal(item.quantidade)
        reserved_elsewhere = active_reserved_quantity(product.id, excluding_order_id=order.id)
        available = parse_decimal(product.estoque_atual) - reserved_elsewhere
        if available < needed:
            raise ValueError(f'Estoque insuficiente para {product.nome}: disponivel {available}, necessario {needed}.')
        reservation = StockReservation.query.filter_by(work_order_item_id=item.id).first()
        if not reservation:
            reservation = StockReservation(work_order=order, work_order_item=item, product=product)
            db.session.add(reservation)
        reservation.quantity = needed
        reservation.status = 'ATIVA'
        reservation.consumed_at = None
        reservation.released_at = None
        reservations.append(reservation)
    db.session.flush()
    return reservations


def consume_order_parts(order: WorkOrder, user_id: int | None = None) -> list[str]:
    if order.estoque_baixado:
        return []
    reservations = reserve_order_parts(order)
    warnings = []
    for reservation in reservations:
        product = _lock_product(reservation.product_id)
        quantity = parse_decimal(reservation.quantity)
        balance = parse_decimal(product.estoque_atual) - quantity
        if balance < 0:
            raise ValueError(f'Estoque insuficiente para {product.nome}.')
        product.estoque_atual = balance
        reservation.status = 'CONSUMIDA'
        reservation.consumed_at = datetime.now()
        db.session.add(InventoryMovement(
            product=product, work_order=order, movement_type='SAIDA_OS', quantity=-quantity,
            balance_after=balance, reference=order.numero, unit_cost=product.custo, user_id=user_id,
        ))
        if balance < parse_decimal(product.estoque_minimo):
            warnings.append(f'{product.nome}: estoque abaixo do minimo')
    order.estoque_baixado = True
    return warnings


def release_order_reservations(order: WorkOrder) -> int:
    count = 0
    for reservation in order.stock_reservations:
        if reservation.status == 'ATIVA':
            reservation.status = 'LIBERADA'
            reservation.released_at = datetime.now()
            count += 1
    return count


def adjust_stock(product: Product, new_balance, reason: str, user_id: int | None = None):
    product = _lock_product(product.id)
    new_balance = parse_decimal(new_balance)
    if new_balance < 0:
        raise ValueError('O saldo de estoque nao pode ser negativo.')
    old_balance = parse_decimal(product.estoque_atual)
    product.estoque_atual = new_balance
    movement = InventoryMovement(
        product=product, movement_type='AJUSTE', quantity=new_balance - old_balance,
        balance_after=new_balance, reference='AJUSTE_MANUAL', notes=(reason or '').strip() or None,
        user_id=user_id,
    )
    db.session.add(movement)
    return movement


def receive_stock(supplier: Supplier, items, numero_nota: str | None, data_entrada, user_id: int | None = None) -> StockEntry:
    """Lança uma entrada de mercadoria: soma ao saldo, atualiza o custo e registra a movimentação.

    items: lista de (produto, quantidade, custo unitário).
    """
    if not items:
        raise ValueError('Inclua ao menos uma peça na entrada.')
    numero_nota = (numero_nota or '').strip()[:50] or None
    entry = StockEntry(supplier_id=supplier.id, numero_nota=numero_nota, data_emissao=data_entrada,
                       data_entrada=data_entrada, valor_total=Decimal('0'), status='CONCLUIDA')
    db.session.add(entry)
    db.session.flush()
    for product, quantity, unit_cost in items:
        quantity, unit_cost = parse_decimal(quantity), parse_decimal(unit_cost)
        if quantity <= 0 or unit_cost < 0:
            raise ValueError(f'Quantidade ou custo inválido para {product.nome}.')
        product = _lock_product(product.id)
        balance = parse_decimal(product.estoque_atual) + quantity
        product.estoque_atual = balance
        product.custo = unit_cost
        total = (quantity * unit_cost).quantize(Decimal('0.01'))
        entry.valor_total += total
        db.session.add(StockEntryItem(stock_entry_id=entry.id, product_id=product.id, quantidade=quantity,
                                      custo_unitario=unit_cost, total_item=total))
        db.session.add(InventoryMovement(
            product=product, movement_type='ENTRADA', quantity=quantity, balance_after=balance,
            reference=f'NF {numero_nota}' if numero_nota else 'ENTRADA_MANUAL', unit_cost=unit_cost, user_id=user_id,
        ))
    return entry


def register_inventory_change(product: Product, old_balance, movement_type: str, reference: str,
                              user_id: int | None = None, notes: str | None = None):
    """Registra uma alteração de saldo feita por um fluxo legado/importação."""
    old_balance = parse_decimal(old_balance)
    balance = parse_decimal(product.estoque_atual)
    if balance == old_balance:
        return None
    movement = InventoryMovement(
        product=product, movement_type=movement_type, quantity=balance - old_balance,
        balance_after=balance, reference=reference[:100], notes=(notes or '').strip() or None,
        user_id=user_id,
    )
    db.session.add(movement)
    return movement


def ensure_warranty(order: WorkOrder):
    if not order.data_saida:
        order.data_saida = date.today()
    settings = get_system_settings()
    warranty = order.warranty
    if not warranty:
        warranty = ServiceWarranty(
            work_order=order, starts_at=order.data_saida,
            ends_at=order.data_saida + timedelta(days=max(settings.warranty_days or 90, 1)),
            terms='Garantia conforme os servicos e pecas descritos na ordem de servico.',
        )
        db.session.add(warranty)
    return warranty


def record_audit(action: str, entity_type: str, entity_id: int | None, user_id: int | None,
                 details: dict | None = None, ip: str | None = None):
    event = AuditEvent(
        action=action, entity_type=entity_type, entity_id=entity_id, user_id=user_id,
        details=json.dumps(details or {}, ensure_ascii=False), ip_address=(ip or '')[:64] or None,
    )
    db.session.add(event)
    return event
