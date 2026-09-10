from datetime import date, datetime, time, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from ..auth import admin_required, current_user, login_required
from ..fleet.models import Vehicle
from ..models import Client, Employee, WorkOrder, db
from .models import Appointment, WorkshopResource
from .services import APPOINTMENT_STATUSES, STAGES, change_stage, convert_to_work_order, save_appointment

scheduling_bp = Blueprint('scheduling', __name__, url_prefix='/agenda')


def _selected_day():
    try:
        return date.fromisoformat(request.args.get('dia', ''))
    except ValueError:
        return date.today()


@scheduling_bp.get('/')
@login_required
def index():
    day = _selected_day()
    start, end = datetime.combine(day, time.min), datetime.combine(day + timedelta(days=1), time.min)
    appointments = Appointment.query.filter(Appointment.start_at >= start, Appointment.start_at < end).order_by(Appointment.start_at).all()
    return render_template('agenda/index.html', appointments=appointments, day=day,
                           previous=day-timedelta(days=1), following=day+timedelta(days=1))


@scheduling_bp.route('/novo', methods=['GET', 'POST'])
@login_required
def new():
    appointment = Appointment(start_at=datetime.now().replace(minute=0, second=0, microsecond=0),
                              end_at=(datetime.now()+timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
    return _form(appointment)


@scheduling_bp.route('/<int:appointment_id>/editar', methods=['GET', 'POST'])
@login_required
def edit(appointment_id):
    return _form(db.get_or_404(Appointment, appointment_id))


def _form(appointment):
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
    clients = Client.query.order_by(Client.nome).all()
    employees = Employee.query.filter_by(ativo=True).order_by(Employee.nome).all()
    resources = WorkshopResource.query.filter_by(ativo=True).order_by(WorkshopResource.nome).all()
    vehicles = Vehicle.query.filter_by(ativo=True).order_by(Vehicle.descricao).all()
    return render_template('agenda/form.html', appointment=appointment, clients=clients, employees=employees,
                           resources=resources, vehicles=vehicles, statuses=APPOINTMENT_STATUSES), code


@scheduling_bp.post('/<int:appointment_id>/converter-os')
@login_required
def convert(appointment_id):
    appointment = db.get_or_404(Appointment, appointment_id)
    order = convert_to_work_order(appointment, current_user().id)
    db.session.commit()
    flash('O.S. criada a partir do agendamento.', 'success')
    return redirect(url_for('web.work_orders_show', work_order_id=order.id))


@scheduling_bp.get('/patio')
@login_required
def board():
    orders = WorkOrder.query.filter(~WorkOrder.status.in_(['ENTREGUE', 'CANCELADA'])).order_by(WorkOrder.promised_at, WorkOrder.id).all()
    return render_template('agenda/patio.html', orders=orders, stages=STAGES, now=datetime.now())


@scheduling_bp.post('/patio/<int:work_order_id>/etapa')
@login_required
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
    return redirect(url_for('scheduling.board'))


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
