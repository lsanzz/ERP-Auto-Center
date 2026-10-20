"""Dados do Painel do pátio: boxes, quadro por etapa, chegadas, técnicos e estoque baixo."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func

from ..models import Employee, Product, WorkOrder, db
from .models import Appointment, WorkshopResource, WorkOrderStageHistory

ACTIVE_EXCLUDED = ('ENTREGUE', 'CANCELADA')
BOARD_STAGES = ('RECEPCAO', 'DIAGNOSTICO', 'AGUARDANDO_APROVACAO', 'AGUARDANDO_PECA',
                'EM_EXECUCAO', 'CONTROLE_QUALIDADE', 'PRONTO')
STAGE_LABELS = {
    'RECEPCAO': 'Recepção', 'DIAGNOSTICO': 'Diagnóstico', 'AGUARDANDO_APROVACAO': 'Aguardando aprovação',
    'AGUARDANDO_PECA': 'Aguardando peça', 'EM_EXECUCAO': 'Em execução',
    'CONTROLE_QUALIDADE': 'Controle de qualidade', 'PRONTO': 'Pronto', 'ENTREGUE': 'Entregue',
}
# Próxima ação de cada etapa: (rótulo do botão, etapa de destino).
NEXT_ACTION = {
    'RECEPCAO': ('Iniciar diagnóstico', 'DIAGNOSTICO'),
    'DIAGNOSTICO': ('Pedir aprovação', 'AGUARDANDO_APROVACAO'),
    'AGUARDANDO_APROVACAO': ('Iniciar reparo', 'EM_EXECUCAO'),
    'AGUARDANDO_PECA': ('Retomar reparo', 'EM_EXECUCAO'),
    'EM_EXECUCAO': ('Enviar para qualidade', 'CONTROLE_QUALIDADE'),
    'CONTROLE_QUALIDADE': ('Marcar pronto', 'PRONTO'),
    'PRONTO': ('Entregar', 'ENTREGUE'),
}
# Etapas em que o carro ocupa o box com alguém trabalhando nele.
WORKING_STAGES = ('DIAGNOSTICO', 'EM_EXECUCAO', 'CONTROLE_QUALIDADE')
WAITING_STAGES = ('AGUARDANDO_APROVACAO', 'AGUARDANDO_PECA')


def _elapsed(since, now):
    if not since:
        return None
    minutes = max(int((now - since).total_seconds() // 60), 0)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h{minutes:02d}' if hours else f'{minutes} min'


def _card(order, stage_started, now):
    label, target = NEXT_ACTION.get(order.current_stage, (None, None))
    return {
        'order': order,
        'stage_label': STAGE_LABELS.get(order.current_stage, order.current_stage),
        'elapsed': _elapsed(stage_started.get(order.id), now),
        'overdue': bool(order.promised_at and order.promised_at < now and order.current_stage != 'PRONTO'),
        'waiting': order.current_stage in WAITING_STAGES,
        'action_label': label,
        'action_stage': target,
        'client_name': order.client_nome or (order.client.nome if order.client else ''),
    }


def build_floor(now=None):
    now = now or datetime.now()
    day_start = datetime.combine(now.date(), time.min)
    day_end = day_start + timedelta(days=1)

    orders = WorkOrder.query.filter(~WorkOrder.status.in_(ACTIVE_EXCLUDED),
                                    WorkOrder.current_stage != 'ENTREGUE').order_by(
        WorkOrder.promised_at, WorkOrder.id).all()
    open_stages = WorkOrderStageHistory.query.filter(
        WorkOrderStageHistory.ended_at.is_(None),
        WorkOrderStageHistory.work_order_id.in_([o.id for o in orders] or [0])).all()
    stage_started = {entry.work_order_id: entry.started_at for entry in open_stages}
    cards = [_card(order, stage_started, now) for order in orders]

    bays = []
    resources = WorkshopResource.query.filter_by(ativo=True).order_by(WorkshopResource.nome).all()
    for resource in resources:
        in_bay = [c for c in cards if c['order'].workshop_resource_id == resource.id
                  and c['order'].current_stage != 'PRONTO']
        bays.append({'resource': resource, 'card': in_bay[0] if in_bay else None, 'queue': len(in_bay[1:])})
    busy_bays = sum(1 for bay in bays if bay['card'])

    board = [{'stage': stage, 'label': STAGE_LABELS[stage],
              'cards': [c for c in cards if c['order'].current_stage == stage]} for stage in BOARD_STAGES]

    ready = [c for c in cards if c['order'].current_stage == 'PRONTO']
    ready_total = sum((c['order'].total_geral or Decimal('0')) for c in ready)
    delivered_today = db.session.query(func.coalesce(func.sum(WorkOrder.total_geral), 0)).filter(
        WorkOrder.status == 'ENTREGUE', WorkOrder.data_saida == now.date()).scalar()

    appointments = Appointment.query.filter(
        Appointment.start_at >= day_start, Appointment.start_at < day_end,
        Appointment.status.in_(['AGENDADO', 'CONFIRMADO'])).order_by(Appointment.start_at).all()
    booked = Appointment.query.filter(Appointment.start_at >= day_start, Appointment.start_at < day_end,
                                      Appointment.status.notin_(['CANCELADO', 'NAO_COMPARECEU'])).all()
    booked_hours = sum((a.end_at - a.start_at).total_seconds() for a in booked) / 3600

    technicians = []
    for employee in Employee.query.filter_by(ativo=True).order_by(Employee.nome).all():
        mine = [c for c in cards if c['order'].employee_id == employee.id]
        working = next((c for c in mine if c['order'].current_stage in WORKING_STAGES), None)
        technicians.append({'employee': employee, 'working': working, 'open_count': len(mine)})

    low_stock = Product.query.filter(Product.ativo.is_(True), Product.estoque_minimo > 0,
                                     Product.estoque_atual < Product.estoque_minimo).order_by(
        (Product.estoque_atual / Product.estoque_minimo), Product.nome).limit(6).all()

    activity = WorkOrderStageHistory.query.order_by(WorkOrderStageHistory.started_at.desc()).limit(8).all()

    return {
        'now': now,
        'kpis': {
            'on_site': len(cards),
            'waiting_bay': sum(1 for c in cards if not c['order'].workshop_resource_id and c['order'].current_stage != 'PRONTO'),
            'busy_bays': busy_bays,
            'total_bays': len(bays),
            'ready_count': len(ready),
            'ready_total': ready_total,
            'delivered_today': delivered_today or Decimal('0'),
            'overdue': sum(1 for c in cards if c['overdue']),
        },
        'bays': bays,
        'board': board,
        'appointments': appointments,
        'booked_hours': booked_hours,
        'booked_count': len(booked),
        'technicians': technicians,
        'low_stock': low_stock,
        'activity': [{'entry': e, 'label': STAGE_LABELS.get(e.stage, e.stage),
                      'ago': _elapsed(e.started_at, now)} for e in activity],
        'stage_labels': STAGE_LABELS,
    }
