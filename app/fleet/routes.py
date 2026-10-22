import json
from datetime import date

import click
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from ..auth import current_user, login_required, admin_required, permission_required
from ..models import Client, WorkOrder, Budget, db
from .models import Vehicle
from .services import CATEGORIES, import_legacy_vehicles, save_vehicle, record_odometer

fleet_bp = Blueprint('fleet', __name__, url_prefix='/veiculos')


@fleet_bp.get('/')
@login_required
@permission_required('vehicles.view')
def index():
    q = request.args.get('q', '').strip()
    query = Vehicle.query.join(Client)
    if q:
        term = f'%{q}%'
        query = query.filter(or_(Vehicle.placa.ilike(term), Vehicle.descricao.ilike(term),
                                 Vehicle.chassi.ilike(term), Client.nome.ilike(term),
                                 Client.telefone.ilike(term)))
    if request.args.get('client_id', type=int):
        query = query.filter(Vehicle.client_id == request.args.get('client_id', type=int))
    status = request.args.get('status', 'ativos')
    if status != 'todos':
        query = query.filter(Vehicle.ativo.is_(status != 'inativos'))
    pagination = db.paginate(query.order_by(Vehicle.descricao).statement,
                             page=request.args.get('page', 1, type=int), per_page=25, error_out=False)
    return render_template('veiculos/index.html', vehicles=pagination.items, pagination=pagination, q=q, status=status)


@fleet_bp.route('/novo', methods=['GET', 'POST'])
@login_required
@permission_required('vehicles.manage')
def new():
    # Vindo da consulta de placa: já chega com placa e dados do veículo.
    args = request.args
    return _form(Vehicle(placa=(args.get('placa') or '')[:10] or None, descricao=(args.get('descricao') or '')[:160],
                         marca=(args.get('marca') or '')[:80] or None, modelo=(args.get('modelo') or '')[:100] or None))


@fleet_bp.route('/<int:vehicle_id>/editar', methods=['GET', 'POST'])
@login_required
@permission_required('vehicles.manage')
def edit(vehicle_id):
    return _form(db.get_or_404(Vehicle, vehicle_id))


def _form(vehicle):
    status = 200
    if request.method == 'POST':
        try:
            if vehicle.id and request.form.get('version') != str(vehicle.version):
                raise StaleDataError()
            save_vehicle(vehicle, request.form, current_user().id)
            db.session.commit()
            flash('Veículo salvo.', 'success')
            return redirect(url_for('fleet.show', vehicle_id=vehicle.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
            status = 400
        except (IntegrityError, StaleDataError):
            db.session.rollback()
            flash('Cadastro duplicado ou alterado por outro usuário. Confira os dados e recarregue a página.', 'error')
            status = 409
    return render_template('veiculos/form.html', vehicle=vehicle,
                           values=request.form if request.method == 'POST' else vehicle.to_dict(),
                           clients=Client.query.order_by(Client.nome).all(), categories=CATEGORIES), status


@fleet_bp.get('/<int:vehicle_id>')
@login_required
@permission_required('vehicles.view')
def show(vehicle_id):
    vehicle = db.get_or_404(Vehicle, vehicle_id)
    # One chronological stream, bounded and paginated at the database level.
    orders = db.select(db.literal('OS').label('kind'), WorkOrder.id.label('id'),
                       WorkOrder.created_at.label('created_at')).where(WorkOrder.vehicle_id == vehicle.id)
    budgets = db.select(db.literal('ORC').label('kind'), Budget.id.label('id'),
                        Budget.created_at.label('created_at')).where(Budget.vehicle_id == vehicle.id)
    timeline_query = orders.union_all(budgets).subquery()
    page = max(1, request.args.get('page', 1, type=int) or 1)
    rows = db.session.execute(db.select(timeline_query).order_by(
        timeline_query.c.created_at.desc(), timeline_query.c.kind, timeline_query.c.id.desc()
    ).offset((page - 1) * 25).limit(26)).all()
    timeline = []
    for row in rows[:25]:
        model = WorkOrder if row.kind == 'OS' else Budget
        timeline.append((row.kind, db.session.get(model, row.id)))
    return render_template('veiculos/show.html', vehicle=vehicle, timeline=timeline,
                           page=page, has_next=len(rows) > 25, today=date.today().isoformat())


@fleet_bp.post('/<int:vehicle_id>/quilometragem')
@login_required
@permission_required('vehicles.manage')
def odometer(vehicle_id):
    vehicle = db.get_or_404(Vehicle, vehicle_id)
    try:
        if request.form.get('version') != str(vehicle.version):
            raise StaleDataError()
        day = date.fromisoformat(request.form.get('recorded_on', ''))
        record_odometer(vehicle, request.form.get('quilometragem'), current_user().id,
                        day, request.form.get('observacoes'))
        db.session.commit()
        flash('Quilometragem registrada.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    except StaleDataError:
        db.session.rollback()
        flash('O veículo foi atualizado por outro usuário. Confira o histórico antes de repetir.', 'error')
    return redirect(url_for('fleet.show', vehicle_id=vehicle.id))


@fleet_bp.post('/<int:vehicle_id>/situacao')
@login_required
@admin_required
def toggle_active(vehicle_id):
    vehicle = db.get_or_404(Vehicle, vehicle_id)
    if request.form.get('version') != str(vehicle.version):
        abort(409)
    vehicle.ativo = not vehicle.ativo
    db.session.commit()
    return redirect(url_for('fleet.show', vehicle_id=vehicle.id))


@fleet_bp.cli.command('importar-legado')
@click.option('--aplicar', is_flag=True, help='Persiste os vínculos; sem esta opção apenas simula.')
def backfill(aplicar):
    """Importa veículos a partir de orçamento/OS sem substituir snapshots."""
    try:
        result = import_legacy_vehicles()
        if aplicar:
            db.session.commit()
        else:
            db.session.rollback()
        click.echo(json.dumps({'aplicado': aplicar, **result}, ensure_ascii=False, indent=2))
    except Exception:
        db.session.rollback()
        raise


@fleet_bp.get('/buscar')
@login_required
@permission_required('vehicles.view')
def lookup():
    client_id = request.args.get('client_id', type=int)
    if not client_id:
        return {'items': []}
    q = request.args.get('q', '').strip()
    query = Vehicle.query.filter_by(client_id=client_id, ativo=True)
    if q:
        query = query.filter(or_(Vehicle.placa.ilike(f'%{q}%'), Vehicle.descricao.ilike(f'%{q}%')))
    return {'items': [{'id': v.id, 'placa': v.placa, 'descricao': v.descricao}
                      for v in query.order_by(Vehicle.descricao).limit(50)]}
