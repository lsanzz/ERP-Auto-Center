"""Dados do Painel do pátio: carros não entregues em três colunas (Aguardando, Em andamento, Atendida)."""
from datetime import datetime

from ..models import WorkOrder
from .models import WorkOrderStageHistory

ACTIVE_EXCLUDED = ('ENTREGUE', 'CANCELADA')
STAGE_LABELS = {
    'RECEPCAO': 'Recepção', 'DIAGNOSTICO': 'Diagnóstico', 'AGUARDANDO_APROVACAO': 'Aguardando aprovação',
    'AGUARDANDO_PECA': 'Aguardando peça', 'EM_EXECUCAO': 'Em execução',
    'CONTROLE_QUALIDADE': 'Controle de qualidade', 'PRONTO': 'Pronto', 'ENTREGUE': 'Entregue',
}
WAITING_STAGES = ('AGUARDANDO_APROVACAO', 'AGUARDANDO_PECA')


def _elapsed(since, now):
    if not since:
        return None
    minutes = max(int((now - since).total_seconds() // 60), 0)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h{minutes:02d}' if hours else f'{minutes} min'


def _card(order, stage_started, now):
    return {
        'order': order,
        'stage_label': STAGE_LABELS.get(order.current_stage, order.current_stage),
        'elapsed': _elapsed(stage_started.get(order.id), now),
        'overdue': bool(order.promised_at and order.promised_at < now and order.current_stage != 'PRONTO'),
        'waiting': order.current_stage in WAITING_STAGES,
        'client_name': order.client_nome or (order.client.nome if order.client else ''),
    }


def build_floor(now=None):
    """Três colunas (Aguardando, Em andamento, Atendida) com os carros que ainda não foram entregues."""
    from .services import FLOOR_COLUMNS
    now = now or datetime.now()
    orders = WorkOrder.query.filter(~WorkOrder.status.in_(ACTIVE_EXCLUDED),
                                    WorkOrder.current_stage != 'ENTREGUE').order_by(
        WorkOrder.promised_at, WorkOrder.id).all()
    open_stages = WorkOrderStageHistory.query.filter(
        WorkOrderStageHistory.ended_at.is_(None),
        WorkOrderStageHistory.work_order_id.in_([o.id for o in orders] or [0])).all()
    stage_started = {entry.work_order_id: entry.started_at for entry in open_stages}
    cards = [_card(order, stage_started, now) for order in orders]
    columns = [{'key': key, 'label': label, 'cards': [c for c in cards if c['order'].current_stage in stages]}
               for key, label, stages, _ in FLOOR_COLUMNS]
    return {'now': now, 'columns': columns, 'overdue': sum(1 for c in cards if c['overdue'])}
