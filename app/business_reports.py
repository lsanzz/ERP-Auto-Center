"""Period reports and searchable business history; no external side effects."""
import calendar
import csv
import io
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from flask import Blueprint, Response, abort, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from .auth import admin_required, permission_required
from .models import (BankAccount, Budget, ChartOfAccount, Client, FinancialEntry,
                     FiscalDocument, PurchaseRequest, User, WorkOrder, db)
from .operations.models import AuditEvent

business_bp = Blueprint('business', __name__)
ZERO = Decimal('0')


def period():
    today = date.today()
    try:
        start = date.fromisoformat(request.args.get('start') or today.replace(day=1).isoformat())
        end = date.fromisoformat(request.args.get('end') or today.isoformat())
    except ValueError:
        abort(400, description='Informe datas válidas no formato AAAA-MM-DD.')
    if end < start or (end - start).days > 366:
        abort(400, description='Selecione um período de até 367 dias, com início anterior ao fim.')
    return start, end


def net_expression():
    return (func.coalesce(FinancialEntry.valor_baixa, FinancialEntry.valor)
            + func.coalesce(FinancialEntry.juros, 0) - func.coalesce(FinancialEntry.desconto, 0)
            - func.coalesce(FinancialEntry.taxa, 0) + func.coalesce(FinancialEntry.acrescimo, 0))


def report_data(start, end, basis='competencia', account_id=None):
    """Never mix nominal accrual revenue with net settled cash amounts."""
    cash = basis == 'caixa'
    field = FinancialEntry.payment_receipt_at if cash else FinancialEntry.competence_on
    amount = net_expression() if cash else FinancialEntry.valor
    query = FinancialEntry.query.filter(FinancialEntry.status != 'CANCELADO')
    if cash:
        query = query.filter(FinancialEntry.status.in_(['PAGO', 'RECEBIDO']))
    if account_id:
        query = query.filter_by(bank_account_id=account_id)
    query = query.filter(field.between(start, end))
    rows = query.with_entities(FinancialEntry.entry_type,
        func.coalesce(ChartOfAccount.name, FinancialEntry.categoria, 'Sem classificação'),
        func.sum(amount)).outerjoin(ChartOfAccount, FinancialEntry.chart_account_id == ChartOfAccount.id).group_by(
        FinancialEntry.entry_type, ChartOfAccount.name, FinancialEntry.categoria).order_by(FinancialEntry.entry_type).all()
    # Merge legacy categories mapped to the same chart account.
    grouped = {}
    for kind, category, value in rows:
        grouped[kind, category] = grouped.get((kind, category), ZERO) + value
    rows = [(kind, category, value) for (kind, category), value in sorted(grouped.items())]
    revenue = sum((v for k, _, v in rows if k == 'RECEBER'), ZERO)
    expense = sum((v for k, _, v in rows if k == 'PAGAR'), ZERO)
    daily = query.with_entities(field, FinancialEntry.entry_type, func.sum(amount)).group_by(field, FinancialEntry.entry_type).all()
    values = {(day, kind): value for day, kind, value in daily}
    accumulated = ZERO
    days = []
    for offset in range((end-start).days+1):
        day = start + timedelta(days=offset)
        incoming, outgoing = values.get((day, 'RECEBER'), ZERO), values.get((day, 'PAGAR'), ZERO)
        accumulated += incoming-outgoing
        days.append(dict(day=day, incoming=incoming, outgoing=outgoing, accumulated=accumulated))
    return dict(rows=rows, revenue=revenue, expense=expense, result=revenue-expense, days=days)


def csv_download(filename, headers, rows):
    def safe(value):
        text = '' if value is None else str(value)
        return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(headers)
    for row in rows:
        writer.writerow([safe(value) for value in row])
    return Response('\ufeff' + output.getvalue(), content_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store'})


@business_bp.get('/financeiro/balancete')
@permission_required('reports.view')
def balance():
    start, end = period()
    basis = request.args.get('basis', 'competencia')
    if basis not in {'competencia', 'caixa'}:
        abort(400, description='Regime inválido.')
    account_id = request.args.get('account', type=int)
    data = report_data(start, end, basis, account_id)
    if request.args.get('export') == 'csv':
        return csv_download('balancete.csv', ['Tipo', 'Classificação', 'Valor', 'Regime', 'Início', 'Fim'],
            [(k, c, v, basis, start, end) for k, c, v in data['rows']])
    return render_template('financeiro/balance.html', report=data, start=start, end=end, basis=basis,
        accounts=BankAccount.query.order_by(BankAccount.nome).all())


@business_bp.get('/financeiro/calendario')
@permission_required('finance.view')
def finance_calendar():
    try:
        month = date.fromisoformat((request.args.get('month') or date.today().strftime('%Y-%m')) + '-01')
        previous = (month-timedelta(days=1)).strftime('%Y-%m')
        end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        following = (end+timedelta(days=1)).strftime('%Y-%m')
    except (ValueError, OverflowError):
        abort(400, description='Mês inválido.')
    rows = FinancialEntry.query.with_entities(FinancialEntry.vencimento, FinancialEntry.entry_type,
        func.sum(FinancialEntry.valor), func.count(FinancialEntry.id)).filter(
        FinancialEntry.status == 'PENDENTE', FinancialEntry.vencimento.between(month, end)).group_by(
        FinancialEntry.vencimento, FinancialEntry.entry_type).all()
    values = {(day, kind): (amount, count) for day, kind, amount, count in rows}
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(month.year, month.month):
        weeks.append([dict(day=day, active=day.month == month.month,
            incoming=values.get((day, 'RECEBER'), (ZERO, 0)), outgoing=values.get((day, 'PAGAR'), (ZERO, 0))) for day in week])
    return render_template('financeiro/calendar.html', month=month, previous=previous, following=following,
        weeks=weeks, today=date.today())


@business_bp.get('/historico')
@admin_required
def history():
    from .web import paginate_query
    catalogs = {
        'clientes': (Client, Client.nome, 'Clientes'),
        'os': (WorkOrder, WorkOrder.numero, 'Ordens de serviço'),
        'orcamentos': (Budget, Budget.numero, 'Orçamentos'),
        'compras': (PurchaseRequest, PurchaseRequest.number, 'Compras'),
        'fiscal': (FiscalDocument, FiscalDocument.numero, 'Documentos fiscais'),
    }
    kind = request.args.get('kind', 'eventos')
    search = request.args.get('q', '').strip()[:160]
    start, end = period()
    if kind == 'eventos':
        query = AuditEvent.query.options(joinedload(AuditEvent.user))
        if search:
            query = query.filter(db.or_(AuditEvent.entity_type.contains(search, autoescape=True),
                                       AuditEvent.action.contains(search, autoescape=True)))
        entity_id = request.args.get('entity_id', type=int)
        user_id = request.args.get('user_id', type=int)
        if entity_id is not None:
            query = query.filter_by(entity_id=entity_id)
        if user_id is not None:
            query = query.filter_by(user_id=user_id)
        model = AuditEvent
    elif kind in catalogs:
        model, field, _ = catalogs[kind]
        query = model.query
        if search:
            query = query.filter(field.contains(search, autoescape=True))
    else:
        abort(400, description='Tipo de histórico inválido.')
    query = query.filter(model.created_at >= datetime.combine(start, time.min),
                         model.created_at <= datetime.combine(end, time.max))
    if request.args.get('export') == 'csv':
        if query.count() > 10000:
            abort(400, description='Reduza o período para exportar até 10.000 registros.')
        rows = query.order_by(model.created_at.desc(), model.id.desc()).all()
        if kind == 'eventos':
            return csv_download('historico.csv', ['Data', 'Ação', 'Entidade', 'ID', 'Usuário'],
                [(r.created_at, r.action, r.entity_type, r.entity_id, r.user.nome if r.user else 'Sistema/cliente') for r in rows])
        return csv_download('registros.csv', ['ID', 'Data', 'Registro', 'Status'],
            [(r.id, r.created_at, getattr(r, catalogs[kind][1].key), getattr(r, 'status', 'Cadastrado')) for r in rows])
    page = paginate_query(query.order_by(model.created_at.desc(), model.id.desc()), per_page=40)
    records = []
    for row in page['items']:
        if kind == 'eventos':
            try:
                details = json.loads(row.details or '{}')
            except (ValueError, TypeError):
                details = {}
            fields = details.get('campos', []) if isinstance(details, dict) else []
            records.append(dict(id=row.id, created_at=row.created_at, label=f'{row.action} · {row.entity_type}',
                status=f'ID {row.entity_id}' if row.entity_id is not None else 'Sem ID registrado',
                author=row.user.nome if row.user else 'Sistema/cliente',
                detail=', '.join(str(f) for f in fields) if isinstance(fields, list) else '', url=None))
        else:
            urls = {'clientes': ('web.clients_show', 'client_id'), 'os': ('web.work_orders_show', 'work_order_id'),
                    'orcamentos': ('web.budgets_show', 'budget_id')}
            target = url_for(urls[kind][0], **{urls[kind][1]: row.id}) if kind in urls else (
                url_for('web.fiscal_index', q=row.numero or row.access_key or '') if kind == 'fiscal' else url_for('management.index'))
            records.append(dict(id=row.id, created_at=row.created_at, label=getattr(row, catalogs[kind][1].key) or f'#{row.id}',
                status=getattr(row, 'status', 'Cadastrado'), author='—', detail='', url=target))
    return render_template('historico/index.html', records=records, pagination=page, kind=kind, search=search,
        start=start, end=end, catalogs=catalogs, users=User.query.order_by(User.nome).all())


@business_bp.get('/financeiro/<int:entry_id>/recibo')
@permission_required('finance.view')
def receipt(entry_id):
    from .services import settled_net_amount
    entry = db.get_or_404(FinancialEntry, entry_id)
    if entry.entry_type != 'RECEBER' or entry.status != 'RECEBIDO' or not entry.payment_receipt_at:
        abort(400, description='O recibo exige uma receita recebida com data de baixa.')
    order = db.session.get(WorkOrder, entry.reference_id) if entry.reference_type == 'OS' and entry.reference_id else None
    return render_template('financeiro/receipt.html', entry=entry, order=order, amount=settled_net_amount(entry))


def render_fiscal_center():
    from .web import paginate_query
    from .fiscal import get_fiscal_config
    start, end = period()
    query = FiscalDocument.query.options(joinedload(FiscalDocument.work_order)).filter(
        FiscalDocument.created_at >= datetime.combine(start, time.min),
        FiscalDocument.created_at <= datetime.combine(end, time.max))
    search = request.args.get('q', '').strip()[:160]
    if search:
        query = query.filter(db.or_(FiscalDocument.numero.contains(search, autoescape=True),
            FiscalDocument.access_key.contains(search, autoescape=True), FiscalDocument.external_id.contains(search, autoescape=True)))
    for key in ('status', 'document_type'):
        if request.args.get(key):
            query = query.filter(getattr(FiscalDocument, key) == request.args[key])
    page = paginate_query(query.order_by(FiscalDocument.id.desc()))
    return render_template('fiscal/center.html', pagination=page, documents=page['items'], start=start, end=end,
        config=get_fiscal_config(), statuses=[r[0] for r in db.session.query(FiscalDocument.status).distinct().order_by(FiscalDocument.status)])
