"""Read-only financial summaries shared by the home and accounts screens."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json

from flask import render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from .models import BankAccount, BankReconciliation, BankTransaction, Client, FinancialEntry, PaymentMethod, Product, PurchaseRequest, WorkOrder, db
from .operations.models import BudgetApproval, StockReservation
from .scheduling.models import Appointment
from .services import settled_net_amount, work_order_receivable_description


def financial_overview(today=None):
    today = today or date.today()
    pending = FinancialEntry.query.filter_by(status='PENDENTE')
    def total(kind, *conditions):
        return pending.with_entities(func.coalesce(func.sum(FinancialEntry.valor), 0)).filter(
            FinancialEntry.entry_type == kind, *conditions).scalar() or Decimal('0')
    accounts = BankAccount.query.filter_by(ativo=True).order_by(BankAccount.nome).all()
    balance = sum((a.saldo_atual for a in accounts), Decimal('0'))
    received = paid = Decimal('0')
    month = today.replace(day=1)
    net = (func.coalesce(FinancialEntry.valor_baixa, FinancialEntry.valor)
           + func.coalesce(FinancialEntry.juros, 0) - func.coalesce(FinancialEntry.desconto, 0)
           - func.coalesce(FinancialEntry.taxa, 0) + func.coalesce(FinancialEntry.acrescimo, 0))
    rows = db.session.query(FinancialEntry.payment_receipt_at, FinancialEntry.entry_type, func.sum(net)).filter(
        FinancialEntry.status.in_(['RECEBIDO', 'PAGO']),
        FinancialEntry.payment_receipt_at.between(min(month, today-timedelta(days=6)), today)
    ).group_by(FinancialEntry.payment_receipt_at, FinancialEntry.entry_type).all()
    amounts = {(day, kind): value for day, kind, value in rows}
    for day, kind, value in rows:
        if day >= month:
            if kind == 'RECEBER': received += value
            else: paid += value
    days = []
    for offset in range(6, -1, -1):
        day = today-timedelta(days=offset)
        days.append(dict(day=day, received=amounts.get((day, 'RECEBER'), 0), paid=amounts.get((day, 'PAGAR'), 0)))
    peak = max([max(d['received'], d['paid']) for d in days] + [1])
    for day in days:
        day['received_height'] = float(day['received']/peak*100)
        day['paid_height'] = float(day['paid']/peak*100)
    horizon = FinancialEntry.vencimento.between(today, today+timedelta(days=30))
    return dict(accounts=accounts, balance=balance, receivable=total('RECEBER'), payable=total('PAGAR'),
                overdue_receivable=total('RECEBER', FinancialEntry.vencimento < today),
                overdue_payable=total('PAGAR', FinancialEntry.vencimento < today),
                projected=balance+total('RECEBER', horizon)-total('PAGAR', horizon),
                received=received, paid=paid, result=received-paid, days=days,
                upcoming=pending.order_by(FinancialEntry.vencimento, FinancialEntry.id).limit(6).all())


def home_context(role):
    today = date.today()
    start = datetime.combine(today, time.min)
    agenda = Appointment.query.options(joinedload(Appointment.client), joinedload(Appointment.vehicle),
        joinedload(Appointment.employee)).filter(Appointment.start_at >= start,
        Appointment.start_at < start+timedelta(days=1)).order_by(Appointment.start_at).all()
    active = WorkOrder.query.filter(~WorkOrder.status.in_(['ENTREGUE', 'CANCELADA']))
    attention = []
    if role == 'MECANICO':
        attention = active.filter(WorkOrder.current_stage.in_(['DIAGNOSTICO', 'EXECUCAO', 'CONTROLE_QUALIDADE'])).order_by(WorkOrder.promised_at).limit(8).all()
    elif role == 'RECEPCIONISTA':
        attention = BudgetApproval.query.filter_by(status='PENDENTE').order_by(BudgetApproval.expires_at).limit(8).all()
    elif role == 'ESTOQUISTA':
        attention = Product.query.filter(Product.ativo.is_(True), Product.estoque_atual <= Product.estoque_minimo).order_by(Product.estoque_atual).limit(8).all()
    elif role == 'FINANCEIRO':
        attention = FinancialEntry.query.filter_by(status='PENDENTE').order_by(FinancialEntry.vencimento).limit(8).all()
    unreconciled = db.session.query(BankTransaction.id).outerjoin(BankReconciliation).filter(BankReconciliation.id.is_(None)).count()
    return dict(today=today, appointments=agenda, ready=active.filter_by(current_stage='PRONTO').count(),
                delayed=active.filter(WorkOrder.promised_at < datetime.now()).count(), role=role, attention=attention,
                low_stock=Product.query.filter(Product.ativo.is_(True), Product.estoque_atual <= Product.estoque_minimo).count(),
                active_reservations=StockReservation.query.filter_by(status='ATIVA').count(),
                open_purchases=PurchaseRequest.query.filter(PurchaseRequest.status.in_(['ABERTA', 'APROVADA'])).count(),
                unreconciled=unreconciled,
                finance=financial_overview(today) if role in {'ADMINISTRADOR', 'FINANCEIRO'} else None)


def render_finance():
    from .web import paginate_query
    today = date.today()
    view = request.args.get('view', 'pending')
    if view not in ('pending', 'overdue', 'received', 'all'): view = 'pending'
    query = FinancialEntry.query.options(joinedload(FinancialEntry.bank_account), joinedload(FinancialEntry.payment_method))
    if view in ('pending', 'overdue'): query = query.filter_by(status='PENDENTE')
    if view == 'overdue': query = query.filter(FinancialEntry.vencimento < today)
    if view == 'received': query = query.filter(FinancialEntry.status.in_(['RECEBIDO', 'PAGO']))
    kind = request.args.get('kind', '')
    if not kind and view in ('pending', 'overdue'):
        kind = 'RECEBER'
    if kind in ('RECEBER', 'PAGAR'): query = query.filter_by(entry_type=kind)
    search = request.args.get('q', '').strip()
    if search:
        term = f'%{search}%'
        matching_orders = select(WorkOrder.id).outerjoin(Client).where(
            db.or_(WorkOrder.client_nome.ilike(term), Client.nome.ilike(term))
        )
        query = query.filter(db.or_(
            FinancialEntry.descricao.ilike(term),
            FinancialEntry.categoria.ilike(term),
            db.and_(FinancialEntry.reference_type == 'OS', FinancialEntry.reference_id.in_(matching_orders)),
        ))
    account = request.args.get('account', type=int)
    if account: query = query.filter_by(bank_account_id=account)
    field = FinancialEntry.payment_receipt_at if view == 'received' else FinancialEntry.vencimento
    for key, after in (('start_date', True), ('end_date', False)):
        try: day = date.fromisoformat(request.args.get(key, ''))
        except ValueError: continue
        query = query.filter(field >= day if after else field <= day)
    page = paginate_query(query.order_by(field.desc() if view == 'received' else field.asc(), FinancialEntry.id))
    order_ids = {entry.reference_id for entry in page['items'] if entry.reference_type == 'OS' and entry.reference_id}
    orders = {order.id: order for order in WorkOrder.query.options(joinedload(WorkOrder.client)).filter(WorkOrder.id.in_(order_ids))} if order_ids else {}
    def entry_description(entry):
        order = orders.get(entry.reference_id) if entry.reference_type == 'OS' else None
        if not order:
            return entry.descricao
        return work_order_receivable_description(order, entry.installment_number, entry.installment_total)
    def imported_details(entry):
        try:
            raw = json.loads(entry.observacoes_pagamento or '{}')
        except (ValueError, TypeError):
            return []
        if not isinstance(raw, dict):
            return []
        return [(label, raw[label]) for label in (
            'Cliente', 'Fornecedor', 'Código fornecedor', 'Documento', 'Observações',
            'Data de Agendamento', 'Emissão', 'Data de Cadastro', 'Data de Alteração',
        ) if raw.get(label)]
    def view_url(value, selected_kind=None):
        args = request.args.to_dict(); args.pop('page', None); args['view'] = value
        if selected_kind:
            args['kind'] = selected_kind
        else:
            args.pop('kind', None)
        return url_for('web.finance_index', **args)
    return render_template('financeiro/overview.html', today=today, view=view, view_url=view_url,
        kind=kind, finance=financial_overview(today), entries=page['items'], pagination=page,
        payment_methods=PaymentMethod.query.filter_by(ativo=True).order_by(PaymentMethod.nome).all(),
        net_amount=settled_net_amount, entry_description=entry_description, imported_details=imported_details)
