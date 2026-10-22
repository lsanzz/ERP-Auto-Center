"""Rotas do assistente: conversa, confirmação e cancelamento de propostas."""
from __future__ import annotations

import json
import time
from collections import defaultdict, deque

from flask import Blueprint, current_app, g, jsonify, request, url_for

from ..auth import current_user, login_required, permission_required
from ..models import AssistantState, PaymentMethod, WorkOrder, db
from ..operations.services import record_audit
from ..services import recalculate_work_order_totals, replace_work_order_items
from . import llm
from .tools import MAX_DRAFTS, OPEN_STATUSES, edit_draft_items

assistant_bp = Blueprint('assistant', __name__, url_prefix='/assistente')

RATE_LIMIT = 12  # mensagens por minuto por usuário; o plano gratuito do Groq tem limite próprio
_recent: dict[int, deque] = defaultdict(deque)


def _rate_limited(user_id: int) -> bool:
    # shortcut: contador em memória por processo; troque por Redis/DB se houver vários servidores.
    now, window = time.monotonic(), _recent[user_id]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= RATE_LIMIT:
        return True
    window.append(now)
    return False


def _friendly_error(exc: Exception) -> str:
    text = f'{type(exc).__name__} {exc}'
    if '429' in text or 'RESOURCE_EXHAUSTED' in text or 'quota' in text.lower():
        return 'Limite gratuito da I.A. atingido. Tente de novo em alguns minutos.'
    if '401' in text or '403' in text or 'API key' in text or 'API_KEY' in text:
        return 'A chave do Groq é inválida. Verifique GROQ_API_KEY no arquivo .env.'
    return 'O assistente não respondeu agora. Tente novamente em instantes.'


@assistant_bp.app_context_processor
def inject_assistant():
    return {'assistant_enabled': llm.enabled()}


@assistant_bp.post('/mensagem')
@login_required
@permission_required('work_orders.manage')
def message():
    text = ((request.get_json(silent=True) or {}).get('texto') or '').strip()
    if not text:
        return jsonify(erro='Digite ou fale o que precisa.'), 400
    if len(text) > 2000:
        return jsonify(erro='Mensagem muito longa.'), 400
    if not llm.enabled():
        return jsonify(erro='Assistente desligado.'), 503
    user = current_user()
    if _rate_limited(user.id):
        return jsonify(erro='Muitas mensagens seguidas. Aguarde um minuto.'), 429
    try:
        trace = []
        reply, history, drafts, timings = llm.run_turn(text, json.loads(_state(user.id).history_json or '[]'), f'{user.nome} ({user.role})', trace=trace)
    except llm.AssistantUnavailable as exc:
        return jsonify(erro=str(exc)), 503
    except Exception as exc:  # erros do provedor não podem derrubar a página
        current_app.logger.exception('assistant_failed')
        return jsonify(erro=_friendly_error(exc)), 502
    finally:
        db.session.rollback()  # ferramentas só leem; garante que nada pendente seja gravado
    state = _state(user.id, lock=True)
    drafts_saved = json.loads(state.drafts_json or '{}')
    drafts_saved.update(g.pop('ai_new_drafts', {}))
    while len(drafts_saved) > MAX_DRAFTS:
        drafts_saved.pop(next(iter(drafts_saved)))
    state.drafts_json = json.dumps(drafts_saved, default=str)
    state.history_json = json.dumps(history, default=str)
    db.session.commit()
    current_app.logger.info('assistant_turn rounds=%s seconds=%s', len(timings), timings)
    return jsonify(texto=reply, cartoes=drafts, tempos=timings, chamadas=trace)


@assistant_bp.post('/nova')
@login_required
@permission_required('work_orders.manage')
def new_conversation():
    state = _state(current_user().id)
    state.history_json, state.drafts_json = '[]', '{}'
    db.session.commit()
    return jsonify(ok=True)


def _state(user_id: int, lock: bool = False) -> AssistantState:
    query = AssistantState.query.filter_by(user_id=user_id)
    state = (query.with_for_update() if lock and db.session.get_bind().dialect.name == 'mysql' else query).first()
    if not state:
        state = AssistantState(user_id=user_id, history_json='[]', drafts_json='{}')
        db.session.add(state)
    return state


def _pop_draft(draft_id: str) -> dict | None:
    # Uso único e gravado antes de confirmar: reenviar o mesmo pedido não cria outra O.S.
    state = _state(current_user().id, lock=True)
    drafts = json.loads(state.drafts_json or '{}')
    draft = drafts.pop(draft_id, None)
    state.drafts_json = json.dumps(drafts)
    db.session.commit()
    return draft


@assistant_bp.post('/cancelar/<draft_id>')
@login_required
@permission_required('work_orders.manage')
def cancel(draft_id):
    _pop_draft(draft_id)
    return jsonify(ok=True)


@assistant_bp.post('/confirmar/<draft_id>')
@login_required
@permission_required('work_orders.manage')
def confirm(draft_id):
    # Grava o que foi validado no servidor; do cartão editado o navegador só envia índices, variantes e quantidades.
    draft = _pop_draft(draft_id)
    if not draft:
        return jsonify(erro='Proposta expirada ou já usada. Peça de novo ao assistente.'), 404
    user = current_user()
    data = draft['data']
    edits = (request.get_json(silent=True) or {}).get('itens')
    try:
        if edits is not None and draft['kind'] == 'criar_os':
            data = {**data, 'items': edit_draft_items(draft, edits)}
        if draft['kind'] == 'criar_os':
            from ..api import create_work_order_from_payload
            order = create_work_order_from_payload(dict(data))
            action = 'IA_CRIAR_OS'
        elif draft['kind'] == 'alterar_os':
            order = db.session.get(WorkOrder, data['work_order_id'])
            if not order or order.status not in OPEN_STATUSES:
                raise ValueError('A O.S. não está mais aberta para alteração.')
            if order.version != data['version']:
                raise ValueError('A O.S. foi alterada por outra pessoa depois da proposta. Peça de novo ao assistente.')
            if data['payment_method_id'] and not db.session.get(PaymentMethod, data['payment_method_id']):
                raise ValueError('Forma de pagamento não existe mais.')
            order.payment_method_id = data['payment_method_id']
            order.installment_count = data['installment_count']
            order.employee_id = data['employee_id']
            order.observacoes = data['observacoes']
            replace_work_order_items(order, data['items'])
            recalculate_work_order_totals(order)
            action = 'IA_ALTERAR_OS'
        else:
            raise ValueError('Proposta inválida.')
        db.session.flush()
        record_audit(action, 'WORK_ORDER', order.id, user.id, {'origem': 'IA', 'resumo': draft['card'], 'itens': data['items']}, request.remote_addr)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify(erro=str(exc)), 400
    return jsonify(ok=True, numero=order.numero, total=float(order.total_geral),
                   url=url_for('web.work_orders_show', work_order_id=order.id))
