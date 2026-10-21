from datetime import datetime

from sqlalchemy import or_

from ..models import Client, Employee, WorkOrder, db
from ..fleet.models import Vehicle
from ..services import next_number, record_work_order_status
from ..settings import get_system_settings
from .models import Appointment, WorkshopResource, WorkOrderStageHistory

APPOINTMENT_STATUSES = ('AGENDADO', 'CONFIRMADO', 'EM_ATENDIMENTO', 'CONCLUIDO', 'CANCELADO', 'NAO_COMPARECEU')
STAGES = ('RECEPCAO', 'DIAGNOSTICO', 'AGUARDANDO_APROVACAO', 'AGUARDANDO_PECA',
          'EM_EXECUCAO', 'CONTROLE_QUALIDADE', 'PRONTO', 'ENTREGUE')


def parse_local_datetime(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError('Informe data e horário válidos.')


def save_appointment(appointment, data):
    try:
        client = db.session.get(Client, int(data.get('client_id')))
    except (TypeError, ValueError):
        client = None
    if not client:
        raise ValueError('Selecione um cliente.')
    start, end = parse_local_datetime(data.get('start_at')), parse_local_datetime(data.get('end_at'))
    if end <= start:
        raise ValueError('O término deve ser posterior ao início.')
    vehicle = db.session.get(Vehicle, int(data['vehicle_id'])) if data.get('vehicle_id') else None
    if vehicle and vehicle.client_id != client.id:
        raise ValueError('O veículo não pertence ao cliente selecionado.')
    resource = db.session.get(WorkshopResource, int(data['resource_id'])) if data.get('resource_id') else None
    employee = db.session.get(Employee, int(data['employee_id'])) if data.get('employee_id') else None
    if resource and not resource.ativo:
        raise ValueError('O recurso selecionado está inativo.')
    service = (data.get('servico_previsto') or '').strip()
    if not service:
        raise ValueError('Informe o serviço previsto.')
    # MySQL/InnoDB serializes competing reservations using the selected rows.
    if db.session.get_bind().dialect.name == 'mysql':
        if resource:
            db.session.query(WorkshopResource).filter_by(id=resource.id).with_for_update().one()
        if employee:
            db.session.query(Employee).filter_by(id=employee.id).with_for_update().one()
    conflict_fields = []
    if resource:
        conflict_fields.append(Appointment.resource_id == resource.id)
    if employee:
        conflict_fields.append(Appointment.employee_id == employee.id)
    overlap = Appointment.query.filter(
        Appointment.id != (appointment.id or 0), Appointment.status.notin_(['CANCELADO', 'NAO_COMPARECEU']),
        Appointment.start_at < end, Appointment.end_at > start,
        or_(*conflict_fields),
    ).first() if conflict_fields else None
    if overlap:
        raise ValueError('O box/recurso ou responsável já está reservado nesse horário.')
    appointment.client, appointment.vehicle = client, vehicle
    appointment.resource, appointment.employee = resource, employee
    appointment.start_at, appointment.end_at = start, end
    appointment.servico_previsto = service
    appointment.observacoes = (data.get('observacoes') or '').strip() or None
    status = data.get('status') or appointment.status or 'AGENDADO'
    if status not in APPOINTMENT_STATUSES:
        raise ValueError('Situação do agendamento inválida.')
    appointment.status = status
    db.session.add(appointment)
    return appointment


def convert_to_work_order(appointment, user_id):
    if appointment.work_order:
        return appointment.work_order
    order = WorkOrder(
        client_id=appointment.client_id, client_nome=appointment.client.nome,
        vehicle_id=appointment.vehicle_id, employee_id=appointment.employee_id,
        numero=next_number(WorkOrder, get_system_settings().work_order_prefix or 'OS'),
        status='ABERTA', placa=appointment.vehicle.placa if appointment.vehicle else None,
        veiculo_descricao=appointment.vehicle.descricao if appointment.vehicle else None,
        data_entrada=appointment.start_at.date(), promised_at=appointment.end_at,
        workshop_resource_id=appointment.resource_id, observacoes=appointment.observacoes,
    )
    db.session.add(order)
    db.session.flush()
    appointment.work_order, appointment.status = order, 'EM_ATENDIMENTO'
    record_work_order_status(order, order.status, user_id, 'O.S. criada pelo agendamento')
    change_stage(order, 'RECEPCAO', user_id)
    return order


def change_stage(order, stage, user_id, blocking_reason=None, observation=None):
    if stage not in STAGES:
        raise ValueError('Etapa operacional inválida.')
    now = datetime.now()
    current = WorkOrderStageHistory.query.filter_by(work_order_id=order.id, ended_at=None).order_by(
        WorkOrderStageHistory.id.desc()).first()
    if current and current.stage == stage:
        current.blocking_reason = (blocking_reason or '').strip() or None
        current.observation = (observation or '').strip() or None
        return current
    if current:
        current.ended_at = now
    history = WorkOrderStageHistory(work_order=order, user_id=user_id, stage=stage, started_at=now,
                                    blocking_reason=(blocking_reason or '').strip() or None,
                                    observation=(observation or '').strip() or None)
    order.current_stage = stage
    if blocking_reason is not None:
        order.blocking_reason = (blocking_reason or '').strip() or None
    if stage == 'ENTREGUE':
        order.status = 'ENTREGUE'
    elif stage in {'EM_EXECUCAO', 'CONTROLE_QUALIDADE'}:
        order.status = 'EM_ANDAMENTO'
    elif stage == 'AGUARDANDO_PECA':
        order.status = 'AGUARDANDO_PECA'
    db.session.add(history)
    return history


# Colunas do Painel do pátio: (chave, rótulo, etapas que entram nela, etapa ao soltar um carro nela).
FLOOR_COLUMNS = (
    ('aguardando', 'Aguardando', ('RECEPCAO', 'AGUARDANDO_APROVACAO', 'AGUARDANDO_PECA'), 'RECEPCAO'),
    ('andamento', 'Em andamento', ('DIAGNOSTICO', 'EM_EXECUCAO', 'CONTROLE_QUALIDADE'), 'EM_EXECUCAO'),
    ('atendida', 'Atendida', ('PRONTO',), 'PRONTO'),
)


def move_to_column(order, column, user_id):
    """Arrastar no painel: muda a etapa e mantém o status da O.S. coerente com a coluna."""
    spec = next((c for c in FLOOR_COLUMNS if c[0] == column), None)
    if not spec:
        raise ValueError('Coluna inválida.')
    key, _, stages, target = spec
    if order.status in ('ENTREGUE', 'CANCELADA'):
        raise ValueError('Esta O.S. já foi encerrada.')
    if order.current_stage in stages:
        return order
    if key != 'atendida' and order.status == 'FINALIZADA':
        order.data_saida = None  # voltou para o pátio: ainda não saiu
    change_stage(order, target, user_id)
    status = {'aguardando': 'ABERTA', 'atendida': 'FINALIZADA'}.get(key)
    if status and order.status != status:
        from ..services import change_work_order_status
        change_work_order_status(order, status)
        record_work_order_status(order, status, user_id, 'Movida no painel do pátio')
    return order
