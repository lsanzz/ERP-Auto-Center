"""Managerial finance, purchasing, inventory reversal and bank reconciliation."""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func

from .auth import current_user, permission_required
from .models import BankAccount, BankReconciliation, BankTransaction, ChartOfAccount, CommissionEntry, FinancialEntry, Product, PurchaseRequest, PurchaseRequestItem, WorkOrder, db
from .operations.models import InventoryMovement
from .operations.services import record_audit
from .utils import parse_decimal

management_bp = Blueprint('management', __name__, url_prefix='/gestao')


def management_summary(start: date, end: date) -> dict:
    rows = db.session.query(FinancialEntry.entry_type, ChartOfAccount.code, ChartOfAccount.name,
        func.coalesce(func.sum(FinancialEntry.valor), 0)).outerjoin(
        ChartOfAccount, FinancialEntry.chart_account_id == ChartOfAccount.id).filter(
        FinancialEntry.competence_on.between(start, end), FinancialEntry.status != 'CANCELADO').group_by(
        FinancialEntry.entry_type, ChartOfAccount.code, ChartOfAccount.name).all()
    revenue = sum((value for kind, _, _, value in rows if kind == 'RECEBER'), Decimal('0'))
    expense = sum((value for kind, _, _, value in rows if kind == 'PAGAR'), Decimal('0'))
    result = revenue - expense
    return {
        'rows': rows,
        'revenue': revenue,
        'expense': expense,
        'result': result,
        'expense_ratio': (expense / revenue * 100) if revenue else Decimal('0'),
        'margin_rate': (result / revenue * 100) if revenue else Decimal('0'),
    }


def order_profitability(limit: int = 20) -> list[dict]:
    result = []
    orders = WorkOrder.query.filter(WorkOrder.status.in_(['FINALIZADA', 'ENTREGUE'])).order_by(WorkOrder.id.desc()).limit(limit).all()
    for order in orders:
        parts_cost = sum((abs(parse_decimal(row.quantity)) * parse_decimal(row.unit_cost)
            for row in order.inventory_movements if row.movement_type == 'SAIDA_OS'), Decimal('0'))
        commissions = db.session.query(func.coalesce(func.sum(CommissionEntry.amount), 0)).filter_by(work_order_id=order.id).scalar() or Decimal('0')
        fees = db.session.query(func.coalesce(func.sum(FinancialEntry.taxa), 0)).filter_by(reference_type='OS', reference_id=order.id).scalar() or Decimal('0')
        revenue = parse_decimal(order.total_geral)
        cost = parts_cost + parse_decimal(commissions) + parse_decimal(fees)
        margin = revenue - cost
        result.append({
            'order': order,
            'revenue': revenue,
            'cost': cost,
            'margin': margin,
            'margin_rate': (margin / revenue * 100) if revenue else Decimal('0'),
        })
    return result


def create_replenishment_request(user_id: int | None) -> PurchaseRequest:
    purchase = PurchaseRequest(number=f'COMP-{datetime.now():%Y%m%d%H%M%S%f}', requested_by_id=user_id)
    for product in Product.query.filter(Product.ativo.is_(True), Product.estoque_atual < Product.estoque_minimo).all():
        target = parse_decimal(product.estoque_minimo) * 2
        purchase.items.append(PurchaseRequestItem(product=product, quantity=target - parse_decimal(product.estoque_atual)))
    if not purchase.items:
        raise ValueError('Nenhum produto está abaixo do estoque mínimo.')
    db.session.add(purchase)
    return purchase


def receive_purchase(purchase: PurchaseRequest, user_id: int | None) -> None:
    if purchase.status not in {'ABERTA', 'APROVADA'}:
        raise ValueError('Esta solicitação não pode mais ser recebida.')
    for item in purchase.items:
        quantity = parse_decimal(item.quantity) - parse_decimal(item.received_quantity)
        if quantity <= 0: continue
        old = parse_decimal(item.product.estoque_atual)
        item.product.estoque_atual = old + quantity
        item.received_quantity = parse_decimal(item.received_quantity) + quantity
        db.session.add(InventoryMovement(product=item.product, movement_type='ENTRADA_COMPRA', quantity=quantity,
            balance_after=item.product.estoque_atual, unit_cost=item.quoted_unit_cost, reference=purchase.number, user_id=user_id))
    purchase.status = 'RECEBIDA'


def reverse_inventory_movement(movement: InventoryMovement, user_id: int | None, reason: str) -> InventoryMovement:
    if movement.reversal_of_id or InventoryMovement.query.filter_by(reversal_of_id=movement.id).first():
        raise ValueError('Movimento já estornado ou é um estorno.')
    balance = parse_decimal(movement.product.estoque_atual) - parse_decimal(movement.quantity)
    if balance < 0: raise ValueError('O estorno deixaria o estoque negativo.')
    movement.product.estoque_atual = balance
    reversal = InventoryMovement(product=movement.product, movement_type='ESTORNO', quantity=-parse_decimal(movement.quantity),
        balance_after=balance, reference=movement.reference, notes=reason, user_id=user_id, reversal_of=movement)
    db.session.add(reversal)
    return reversal


def import_bank_csv(content: bytes, account: BankAccount) -> int:
    text = content.decode('utf-8-sig'); dialect = csv.Sniffer().sniff(text[:2048], delimiters=',;\t'); count = 0
    for row in csv.DictReader(io.StringIO(text), dialect=dialect):
        raw_date = row.get('data') or row.get('date') or ''; raw_amount = row.get('valor') or row.get('amount') or ''
        description = (row.get('descricao') or row.get('description') or '').strip()
        try:
            posted_on = date.fromisoformat(raw_date) if '-' in raw_date else datetime.strptime(raw_date, '%d/%m/%Y').date()
            amount = parse_decimal(raw_amount)
        except (ValueError, TypeError): continue
        external_id = row.get('id') or hashlib.sha256(f'{account.id}|{posted_on}|{amount}|{description}'.encode()).hexdigest()[:32]
        if not BankTransaction.query.filter_by(bank_account_id=account.id, external_id=external_id).first():
            db.session.add(BankTransaction(bank_account=account, external_id=external_id, posted_on=posted_on,
                description=description or 'Movimento bancário', amount=amount)); count += 1
    return count


@management_bp.get('/')
@permission_required('reports.view')
def index():
    today = date.today()
    try: start, end = date.fromisoformat(request.args.get('start', today.replace(day=1).isoformat())), date.fromisoformat(request.args.get('end', today.isoformat()))
    except ValueError: start, end = today.replace(day=1), today
    transactions = BankTransaction.query.outerjoin(BankReconciliation).filter(BankReconciliation.id.is_(None)).order_by(BankTransaction.posted_on.desc()).limit(30).all()
    return render_template('gestao/index.html', summary=management_summary(start, end), start=start, end=end,
        purchases=PurchaseRequest.query.order_by(PurchaseRequest.id.desc()).limit(20).all(), transactions=transactions,
        accounts=BankAccount.query.filter_by(ativo=True).all(), profitability=order_profitability(),
        entries=FinancialEntry.query.filter(FinancialEntry.status != 'CANCELADO').order_by(FinancialEntry.vencimento.desc()).limit(100).all())


@management_bp.post('/compras/reposicao')
@permission_required('purchases.manage')
def create_purchase():
    try:
        purchase = create_replenishment_request(current_user().id); record_audit('CRIAR_COMPRA', 'SOLICITACAO_COMPRA', None, current_user().id, {'numero': purchase.number}, request.remote_addr)
        db.session.commit(); flash('Solicitação de reposição criada.', 'success')
    except ValueError as exc: db.session.rollback(); flash(str(exc), 'warning')
    return redirect(url_for('management.index'))


@management_bp.post('/compras/<int:purchase_id>/receber')
@permission_required('purchases.manage')
def receive(purchase_id):
    purchase = db.get_or_404(PurchaseRequest, purchase_id)
    try:
        receive_purchase(purchase, current_user().id); record_audit('RECEBER_COMPRA', 'SOLICITACAO_COMPRA', purchase.id, current_user().id, ip=request.remote_addr)
        db.session.commit(); flash('Compra recebida e estoque atualizado.', 'success')
    except ValueError as exc: db.session.rollback(); flash(str(exc), 'error')
    return redirect(url_for('management.index'))


@management_bp.post('/banco/importar')
@permission_required('finance.reconcile')
def bank_import():
    account = db.get_or_404(BankAccount, request.form.get('bank_account_id', type=int)); upload = request.files.get('file')
    if not upload or not upload.filename.lower().endswith('.csv'): flash('Selecione um arquivo CSV.', 'error'); return redirect(url_for('management.index'))
    try: count = import_bank_csv(upload.read(), account); db.session.commit(); flash(f'{count} transação(ões) importada(s).', 'success')
    except (UnicodeDecodeError, csv.Error, ValueError) as exc: db.session.rollback(); flash(f'CSV inválido: {exc}', 'error')
    return redirect(url_for('management.index'))


@management_bp.post('/banco/<int:transaction_id>/conciliar')
@permission_required('finance.reconcile')
def reconcile(transaction_id):
    transaction = db.get_or_404(BankTransaction, transaction_id); entry = db.get_or_404(FinancialEntry, request.form.get('financial_entry_id', type=int))
    if transaction.amount.copy_abs() != parse_decimal(entry.valor).copy_abs(): flash('Os valores da transação e do lançamento são diferentes.', 'error')
    else:
        db.session.add(BankReconciliation(bank_transaction=transaction, financial_entry=entry, reconciled_by_id=current_user().id))
        record_audit('CONCILIAR', 'TRANSACAO_BANCARIA', transaction.id, current_user().id, {'lancamento_id': entry.id}, request.remote_addr)
        db.session.commit(); flash('Transação conciliada.', 'success')
    return redirect(url_for('management.index'))


@management_bp.post('/estoque/movimentos/<int:movement_id>/estornar')
@permission_required('inventory.move')
def reverse_movement(movement_id):
    movement = db.get_or_404(InventoryMovement, movement_id)
    try:
        reverse_inventory_movement(movement, current_user().id, (request.form.get('reason') or '').strip()); record_audit('ESTORNAR_ESTOQUE', 'MOVIMENTO_ESTOQUE', movement.id, current_user().id, ip=request.remote_addr)
        db.session.commit(); flash('Movimento estornado.', 'success')
    except ValueError as exc: db.session.rollback(); flash(str(exc), 'error')
    return redirect(url_for('operations.inventory'))
