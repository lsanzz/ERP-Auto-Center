from datetime import date, datetime, time, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from ..auth import admin_required, current_user, login_required, permission_required
from ..models import Employee, WorkOrder, db
from .floor import build_floor
from .models import Appointment, WorkshopResource
from .services import APPOINTMENT_STATUSES, STAGES, change_stage, convert_to_work_order, move_to_column, save_appointment

scheduling_bp = Blueprint('scheduling', __name__, url_prefix='/agenda')


def _selected_day():
    try:
        return date.fromisoformat(request.args.get('dia', ''))
    except ValueError:
        return date.today()


@scheduling_bp.get('/')
@login_required
@permission_required('scheduling.view')
def index():
    day = _selected_day()
    if request.args.get('visao') == 'mes':
        return _month_view(day)
    start, end = datetime.combine(day, time.min), datetime.combine(day + timedelta(days=1), time.min)
    appointments = Appointment.query.filter(Appointment.start_at >= start, Appointment.start_at < end).order_by(Appointment.start_at).all()
    return render_template('agenda/index.html', appointments=appointments, day=day,
                           previous=day-timedelta(days=1), following=day+timedelta(days=1))


def _month_view(day):
    """Visão mensal: cada dia mostra seus agendamentos; clicar abre a visão do dia."""
    import calendar
    first = day.replace(day=1)
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
    start, end = datetime.combine(weeks[0][0], time.min), datetime.combine(weeks[-1][-1] + timedelta(days=1), time.min)
    by_day = {}
    for item in Appointment.query.filter(Appointment.start_at >= start, Appointment.start_at < end).order_by(Appointment.start_at):
        by_day.setdefault(item.start_at.date(), []).append(item)
    previous = (first - timedelta(days=1)).replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    return render_template('agenda/mes.html', weeks=weeks, by_day=by_day, month=first, previous=previous,
                           following=following, today=date.today())


@scheduling_bp.route('/novo', methods=['GET', 'POST'])
@login_required
@permission_required('scheduling.manage')
def new():
    appointment = Appointment(start_at=datetime.now().replace(minute=0, second=0, microsecond=0),
                              end_at=(datetime.now()+timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
    order = db.session.get(WorkOrder, request.args.get('os', type=int)) if request.args.get('os') else None
    if order:  # agendar a partir da O.S.: já vem com cliente, veículo e serviços
        existing = Appointment.query.filter_by(work_order_id=order.id).first()
        if existing:
            flash('Esta O.S. já tem agendamento.', 'info')
            return redirect(url_for('scheduling.edit', appointment_id=existing.id))
        appointment.client_id, appointment.vehicle_id, appointment.work_order_id = order.client_id, order.vehicle_id, order.id
        appointment.employee_id = order.employee_id
        appointment.servico_previsto = (', '.join(item.descricao for item in order.items if item.item_type == 'SERVICO')
                                        or f'O.S. {order.numero}')[:255]
    return _form(appointment, order)


@scheduling_bp.route('/<int:appointment_id>/editar', methods=['GET', 'POST'])
@login_required
@permission_required('scheduling.manage')
def edit(appointment_id):
    return _form(db.get_or_404(Appointment, appointment_id))


def _form(appointment, order=None):
    code = 200
    if request.method == 'POST':
        try:
            if appointment.id and request.form.get('version') != str(appointment.version):
                raise StaleDataError()
            save_appointment(appointment, request.form)
            db.session.commit()
            flash('Agendamento salvo.', 'success')
            return redirect(url_for('scheduling.index', dia=appointment.start_at.date().isoformat()))
        except (ValueError, StaleDataError, IntegrityError) as exc:
            db.session.rollback()
            flash(str(exc) if isinstance(exc, ValueError) else 'O agendamento foi alterado ou entrou em conflito.', 'error')
            code = 400 if isinstance(exc, ValueError) else 409
    employees = Employee.query.filter_by(ativo=True).order_by(Employee.nome).all()
    resources = WorkshopResource.query.filter_by(ativo=True).order_by(WorkshopResource.nome).all()
    return render_template('agenda/form.html', appointment=appointment, order=order, employees=employees,
                           resources=resources, statuses=APPOINTMENT_STATUSES), code


@scheduling_bp.post('/<int:appointment_id>/converter-os')
@login_required
@permission_required('scheduling.manage')
def convert(appointment_id):
    appointment = db.get_or_404(Appointment, appointment_id)
    order = convert_to_work_order(appointment, current_user().id)
    db.session.commit()
    flash('O.S. criada a partir do agendamento.', 'success')
    return redirect(url_for('web.work_orders_show', work_order_id=order.id))


@scheduling_bp.get('/patio')
@login_required
@permission_required('work_orders.view')
def board():
    orders = WorkOrder.query.filter(~WorkOrder.status.in_(['ENTREGUE', 'CANCELADA']), WorkOrder.current_stage != 'ENTREGUE').order_by(WorkOrder.promised_at, WorkOrder.id).all()
    return render_template('agenda/patio.html', orders=orders, stages=STAGES, now=datetime.now())


@scheduling_bp.post('/patio/<int:work_order_id>/etapa')
@login_required
@permission_required('work_orders.progress')
def board_stage(work_order_id):
    order = db.get_or_404(WorkOrder, work_order_id)
    try:
        change_stage(order, request.form.get('stage'), current_user().id,
                     request.form.get('blocking_reason'), request.form.get('observation'))
        db.session.commit()
        flash('Etapa atualizada.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    if request.form.get('return_to') == 'painel':
        return redirect(url_for('scheduling.floor'))
    return redirect(url_for('scheduling.board'))


@scheduling_bp.post('/patio/<int:work_order_id>/coluna')
@login_required
@permission_required('work_orders.progress')
def board_move(work_order_id):
    # Chamado ao arrastar um carro entre as colunas do Painel do pátio.
    order = db.get_or_404(WorkOrder, work_order_id)
    try:
        move_to_column(order, (request.get_json(silent=True) or {}).get('coluna', ''), current_user().id)
        db.session.commit()
    except (ValueError, StaleDataError) as exc:
        db.session.rollback()
        message = 'A O.S. foi alterada por outra pessoa. Recarregue a página.' if isinstance(exc, StaleDataError) else str(exc)
        return jsonify(erro=message), 409 if isinstance(exc, StaleDataError) else 400
    return jsonify(ok=True, etapa=order.current_stage, status=order.status)


@scheduling_bp.get('/painel')
@login_required
@permission_required('work_orders.view')
def floor():
    return render_template('agenda/painel.html', **build_floor())


@scheduling_bp.route('/recursos', methods=['GET', 'POST'])
@login_required
@admin_required
def resources():
    if request.method == 'POST':
        name = (request.form.get('nome') or '').strip()
        if name:
            db.session.add(WorkshopResource(nome=name, tipo=request.form.get('tipo') or 'BOX', observacoes=request.form.get('observacoes') or None))
            try:
                db.session.commit(); flash('Recurso cadastrado.', 'success')
            except IntegrityError:
                db.session.rollback(); flash('Já existe um recurso com esse nome.', 'error')
    return render_template('agenda/recursos.html', resources=WorkshopResource.query.order_by(WorkshopResource.nome).all())
