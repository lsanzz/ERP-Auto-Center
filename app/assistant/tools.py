"""Ferramentas do assistente: só leitura e propostas. Nada aqui grava no banco.

Cada ferramenta recebe os argumentos vindos do modelo, valida e devolve um dict serializável.
Propostas (propor_os / propor_alteracao_os) ficam guardadas na sessão do usuário e só são gravadas
quando ele clica em Confirmar (ver routes.confirm).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import secrets

from flask import g, session
from sqlalchemy import func

from ..auth import has_permission
from ..fleet.models import Vehicle
from ..fleet.services import normalize_plate
from ..models import Client, Employee, FinancialEntry, PaymentMethod, Product, Service, WorkOrder, db
from ..services import _build_item_values
from ..utils import parse_date

OPEN_STATUSES = ('ABERTA', 'EM_ANDAMENTO', 'AGUARDANDO_PECA')
MAX_DRAFTS = 3
STOP_WORDS = {'DE', 'DO', 'DA', 'DOS', 'DAS', 'E', 'COM', 'PARA'}
GENERIC_WORDS = STOP_WORDS | {'TROCA', 'SERVICO', 'SERVIÇO', 'KIT', 'JOGO', 'MAO', 'MÃO', 'OBRA'}
MAX_OPTIONS = 8


def _money(value) -> float:
    return float(Decimal(value or 0).quantize(Decimal('0.01')))


def _vehicles(client: Client) -> list[dict]:
    return [{'vehicle_id': v.id, 'placa': v.placa, 'descricao': v.descricao} for v in client.vehicles if v.ativo][:5]


def buscar_cliente(texto: str = '') -> dict:
    texto = (texto or '').strip()
    if len(texto) < 2:
        return {'erro': 'Informe ao menos 2 letras do nome do cliente.'}
    plate = normalize_plate_or_none(texto)
    query = Client.query
    if plate:
        owner_ids = [v.client_id for v in Vehicle.query.filter_by(placa=plate)]
        query = query.filter(db.or_(Client.id.in_(owner_ids or [0]), Client.nome.ilike(f'%{texto}%')))
    else:
        for word in texto.split():
            query = query.filter(Client.nome.ilike(f'%{word}%'))
    clients = query.order_by(Client.nome).limit(8).all()
    # Sem CPF, telefone ou e-mail: o modelo não precisa deles para abrir uma O.S.
    return {'clientes': [{'client_id': c.id, 'nome': c.nome, 'veiculos': _vehicles(c)} for c in clients]}


def normalize_plate_or_none(text: str) -> str | None:
    try:
        return normalize_plate(text)
    except ValueError:
        return None


def buscar_veiculo_por_placa(placa: str = '') -> dict:
    plate = normalize_plate_or_none(placa)
    if not plate:
        return {'erro': 'Placa inválida. Use o formato ABC1234 ou ABC1D23.'}
    vehicles = Vehicle.query.filter_by(placa=plate).all()
    return {'placa': plate, 'veiculos': [{'vehicle_id': v.id, 'descricao': v.descricao, 'client_id': v.client_id,
                                          'cliente': v.client.nome if v.client else None} for v in vehicles]}


def buscar_catalogo(tipo: str = 'SERVICO', texto: str = '') -> dict:
    model, price = (Service, 'preco_base') if (tipo or '').upper() == 'SERVICO' else (Product, 'preco_venda')
    query = model.query.filter_by(ativo=True)
    for word in (texto or '').split():
        query = query.filter(model.nome.ilike(f'%{word}%'))
    items = query.order_by(model.nome).limit(10).all()
    return {'tipo': 'SERVICO' if model is Service else 'PECA',
            'itens': [{'id': item.id, 'nome': item.nome, 'preco': _money(getattr(item, price))} for item in items]}


def listar_funcionarios() -> dict:
    return {'funcionarios': [{'employee_id': e.id, 'nome': e.nome, 'funcao': e.funcao}
                             for e in Employee.query.filter_by(ativo=True).order_by(Employee.nome)]}


def listar_formas_pagamento() -> dict:
    return {'formas': [{'payment_method_id': m.id, 'nome': m.nome, 'parcelas_maximas': m.parcelas_maximas if m.permite_parcelamento else 1}
                       for m in PaymentMethod.query.filter_by(ativo=True).order_by(PaymentMethod.nome)]}


def _order_summary(order: WorkOrder, with_items: bool = False) -> dict:
    data = {'numero': order.numero, 'cliente': order.client_nome or (order.client.nome if order.client else None),
            'placa': order.placa, 'veiculo': order.veiculo_descricao, 'status': order.status,
            'data_entrada': order.data_entrada.isoformat() if order.data_entrada else None,
            'forma_pagamento': order.payment_method.nome if order.payment_method else None,
            'total': _money(order.total_geral)}
    if with_items:
        data['itens'] = [{'tipo': i.item_type, 'descricao': i.descricao, 'quantidade': float(i.quantidade),
                          'valor_unitario': _money(i.valor_unitario), 'total': _money(i.total)} for i in order.items]
    return data


def consultar_os(numero: str = '', cliente: str = '', status: str = '') -> dict:
    if numero:
        order = WorkOrder.query.filter_by(numero=str(numero).strip()).first()
        return {'os': _order_summary(order, with_items=True)} if order else {'erro': f'O.S. {numero} não encontrada.'}
    query = WorkOrder.query
    if cliente:
        query = query.filter(WorkOrder.client_nome.ilike(f'%{cliente}%'))
    if status:
        query = query.filter(WorkOrder.status == status.upper())
    orders = query.order_by(WorkOrder.id.desc()).limit(10).all()
    return {'ordens': [_order_summary(o) for o in orders]}


def _period(inicio: str, fim: str) -> tuple[date, date]:
    end = parse_date(fim) or date.today()
    start = parse_date(inicio) or end.replace(day=1)
    if start > end:
        start, end = end, start
    if (end - start).days > 400:
        raise ValueError('Período máximo de 400 dias.')
    return start, end


def relatorio_periodo(inicio: str = '', fim: str = '') -> dict:
    if not has_permission('finance.view'):
        return {'erro': 'Seu usuário não tem acesso a relatórios financeiros.'}
    from ..business_reports import report_data
    from ..finance_overview import financial_overview
    start, end = _period(inicio, fim)
    closed = WorkOrder.query.filter(WorkOrder.status.in_(['FINALIZADA', 'ENTREGUE']), WorkOrder.data_entrada.between(start, end))
    count, total = closed.with_entities(func.count(WorkOrder.id), func.coalesce(func.sum(WorkOrder.total_geral), 0)).one()
    cash = report_data(start, end, basis='caixa')
    overview = financial_overview()
    return {
        'periodo': {'inicio': start.isoformat(), 'fim': end.isoformat()},
        'os_finalizadas': int(count), 'faturamento_os': _money(total),
        'ticket_medio': _money(Decimal(total) / count) if count else 0,
        'recebido_no_caixa': _money(cash['revenue']), 'pago_no_caixa': _money(cash['expense']),
        'resultado_caixa': _money(cash['result']),
        'saldo_atual_contas': _money(overview['balance']),
        'a_receber_em_aberto': _money(overview['receivable']), 'a_pagar_em_aberto': _money(overview['payable']),
        'vencidos_a_receber': _money(overview['overdue_receivable']), 'vencidos_a_pagar': _money(overview['overdue_payable']),
    }


def contas_vencendo(tipo: str = 'RECEBER', dias: int = 7) -> dict:
    if not has_permission('finance.view'):
        return {'erro': 'Seu usuário não tem acesso ao financeiro.'}
    kind = 'PAGAR' if (tipo or '').upper() == 'PAGAR' else 'RECEBER'
    limit = date.today() + timedelta(days=max(0, min(int(dias or 7), 90)))
    entries = FinancialEntry.query.filter(FinancialEntry.status == 'PENDENTE', FinancialEntry.entry_type == kind,
                                          FinancialEntry.vencimento <= limit).order_by(FinancialEntry.vencimento).limit(20).all()
    return {'tipo': kind, 'ate': limit.isoformat(), 'contas': [
        {'descricao': e.descricao, 'vencimento': e.vencimento.isoformat(), 'valor': _money(e.valor),
         'vencida': e.vencimento < date.today()} for e in entries]}


def _catalog_match(kind: str, text: str):
    """Acha o item do catálogo pelo nome dito: nome exato ou um único resultado; vários voltam como candidatos."""
    model = Service if kind == 'SERVICO' else Product
    query = model.query.filter_by(ativo=True)
    exact = query.filter(func.lower(model.nome) == (text or '').strip().lower()).all()
    if len(exact) == 1:
        return exact[0].id, []
    if exact:
        return None, exact
    words = [w for w in (text or '').split() if w.upper() not in STOP_WORDS]
    if not words:
        return None, []
    for word in words:
        query = query.filter(model.nome.ilike(f'%{word}%'))
    found = query.order_by(model.nome).limit(MAX_OPTIONS).all()
    if len(found) == 1:
        return found[0].id, []
    return None, found


def _resolve_items(itens: list, pick: bool = False) -> tuple[list[dict], list[str], list[list]]:
    """Valida os itens como a tela faz e devolve o payload da API, avisos e candidatos de nomes ambíguos.

    Com pick=True, um nome ambíguo vira o candidato de nome mais curto e os demais vão para o cartão escolher;
    sem pick, vira pergunta (erro) para o modelo.
    """
    payload, warnings, candidates = [], [], []
    for raw in itens or []:
        kind = 'SERVICO' if str(raw.get('tipo', '')).upper().startswith('SERV') else 'PECA'
        reference, found = raw.get('catalogo_id') or None, []
        if not reference and raw.get('valor_unitario') in (None, ''):
            reference, found = _catalog_match(kind, raw.get('descricao'))
            if not reference and not found:
                # O modelo às vezes troca serviço por peça (ex.: balanceamento como PECA); o catálogo decide.
                other = 'PECA' if kind == 'SERVICO' else 'SERVICO'
                other_reference, other_found = _catalog_match(other, raw.get('descricao'))
                if other_reference or other_found:
                    kind, reference, found = other, other_reference, other_found
            if found and not pick:
                price = 'preco_base' if kind == 'SERVICO' else 'preco_venda'
                raise ValueError(f'Mais de um item parecido com "{raw.get("descricao")}". Pergunte qual: '
                                 + '; '.join(f'{o.nome} (R$ {_money(getattr(o, price)):.2f})' for o in found))
            if found:
                reference = min(found, key=lambda o: len(o.nome)).id
        reference_id, descricao, qty, unit, discount, total = _build_item_values(
            kind, reference, raw.get('quantidade') or 1, raw.get('desconto') or 0,
            None if reference else raw.get('descricao'), raw.get('valor_unitario'), None)
        if reference_id is None:
            warnings.append(f'"{descricao}" não está no catálogo; será lançado como item avulso.')
        if unit == 0:
            warnings.append(f'"{descricao}" está sem valor (R$ 0,00).')
        payload.append({'item_type': kind, 'reference_id': reference_id, 'descricao': descricao, 'quantidade': str(qty),
                        'valor_unitario': str(unit), 'desconto': str(discount)})
        candidates.append(found)
    return payload, warnings, candidates


def _alternatives(kind: str, reference_id: int | None) -> list[dict]:
    """Variantes do mesmo item no catálogo (ex.: tipos de alinhamento): começam com a mesma palavra e contêm a primeira
    palavra não genérica (óleo não puxa filtro de óleo); primeiro as que mais compartilham palavras com o nome."""
    model = Service if kind == 'SERVICO' else Product
    item = db.session.get(model, reference_id) if reference_id else None
    words = [w for w in item.nome.upper().split() if w not in GENERIC_WORDS] if item else []
    if not words:
        return []
    found = model.query.filter_by(ativo=True).filter(model.nome.ilike(f'{item.nome.split()[0]}%'), model.nome.ilike(f'%{words[0]}%'))
    found = found.order_by(model.nome).limit(40).all()
    found = sorted(found, key=lambda o: -len(set(words) & set(o.nome.upper().split())))[:MAX_OPTIONS]
    if item not in found:
        found[-1:] = [item]
    return _options(kind, found) if len(found) > 1 else []


def _options(kind: str, found: list) -> list[dict]:
    price = 'preco_base' if kind == 'SERVICO' else 'preco_venda'
    return [{'id': o.id, 'nome': o.nome, 'preco': _money(getattr(o, price))} for o in sorted(found, key=lambda o: o.nome.upper())]


def edit_draft_items(draft: dict, edits: list) -> list[dict]:
    """Reaplica no servidor o que o usuário mudou no cartão: só índice, variante (dentre as opções oferecidas) e quantidade."""
    base, choices = draft['data']['items'], draft.get('opcoes') or [[] for _ in draft['data']['items']]
    try:
        pairs = [(int(edit['indice']), int(edit.get('catalogo_id') or 0)) for edit in edits]
    except (TypeError, ValueError, KeyError, AttributeError):
        pairs = []
    indexes = [index for index, _ in pairs]
    if not pairs or len(set(indexes)) != len(indexes) or not all(0 <= i < len(base) for i in indexes):
        raise ValueError('Itens editados inválidos. Peça de novo ao assistente.')
    raw = []
    for (index, chosen), edit in zip(pairs, edits):
        item = base[index]
        reference = chosen or item['reference_id']
        if reference != item['reference_id']:
            if reference not in choices[index]:
                raise ValueError('Variante fora das opções da proposta.')
            # Variante nova usa o preço do catálogo; a original mantém o preço e o desconto da proposta.
            raw.append({'tipo': item['item_type'], 'catalogo_id': reference, 'quantidade': edit.get('quantidade')})
        else:
            raw.append({'tipo': item['item_type'], 'catalogo_id': reference, 'descricao': item['descricao'],
                        'quantidade': edit.get('quantidade'), 'valor_unitario': item['valor_unitario'], 'desconto': item['desconto']})
    return _resolve_items(raw)[0]  # catalogo_id sempre presente: nada ambíguo


def _store_draft(kind: str, data: dict, card: dict, **extra) -> dict:
    drafts = session.get('ai_drafts', {})
    while len(drafts) >= MAX_DRAFTS:
        drafts.pop(next(iter(drafts)))
    draft_id = secrets.token_urlsafe(8)
    drafts[draft_id] = {'kind': kind, 'data': data, 'card': card, **extra}
    session['ai_drafts'] = drafts
    session.modified = True
    return {'draft_id': draft_id, **card}


def propor_os(client_id: int | None = None, cliente_nome: str = '', vehicle_id: int | None = None, placa: str = '',
              veiculo_descricao: str = '', itens: list | None = None, payment_method_id: int | None = None,
              parcelas: int = 1, employee_id: int | None = None, observacoes: str = '', cliente_novo: bool = False) -> dict:
    warnings = []
    spoken = g.get('ai_spoken_plate')
    if spoken and placa and normalize_plate_or_none(placa) != spoken:
        placa = spoken
    client = db.session.get(Client, int(client_id)) if client_id else None
    if client_id and not client:
        return {'erro': 'client_id inexistente. Use buscar_cliente.'}
    if not client and placa and not vehicle_id:
        # Placa ditada já identifica o dono na maioria dos casos.
        owners = Vehicle.query.filter_by(placa=normalize_plate_or_none(placa)).all() if normalize_plate_or_none(placa) else []
        if len(owners) == 1 and not cliente_novo:
            client, vehicle_id = owners[0].client, owners[0].id
    if not client:
        nome = (cliente_nome or '').strip().upper()
        if not nome:
            return {'erro': 'Informe o cliente.'}
        same = Client.query.filter(func.lower(Client.nome) == nome.lower()).all()
        similar = buscar_cliente(nome).get('clientes', [])
        if same:
            client = same[0]
        elif len(similar) == 1 and not cliente_novo:
            client = db.session.get(Client, similar[0]['client_id'])
        elif similar and not cliente_novo:
            return {'erro': 'Existem clientes parecidos. Pergunte ao usuário qual é, ou se é um cliente novo.',
                    'candidatos': [c['nome'] for c in similar]}
        else:
            warnings.append(f'Cliente novo será cadastrado: {nome}.')
    vehicle = db.session.get(Vehicle, int(vehicle_id)) if vehicle_id else None
    if vehicle and client and vehicle.client_id != client.id:
        return {'erro': 'Este veículo pertence a outro cliente. Confirme com o usuário.'}
    plate = vehicle.placa if vehicle else None
    if placa and not vehicle:
        plate = normalize_plate_or_none(placa)
        if not plate:
            return {'erro': f'Placa "{placa}" inválida. Peça a placa novamente (ABC1234 ou ABC1D23).'}
    method = db.session.get(PaymentMethod, int(payment_method_id)) if payment_method_id else None
    if payment_method_id and not method:
        return {'erro': 'payment_method_id inexistente. Use listar_formas_pagamento.'}
    employee = db.session.get(Employee, int(employee_id)) if employee_id else None
    try:
        items, item_warnings, candidates = _resolve_items(itens, pick=True)
    except ValueError as exc:
        return {'erro': str(exc)}
    if not items:
        return {'erro': 'Inclua ao menos um serviço ou peça.'}
    warnings += item_warnings
    installments = max(1, min(int(parcelas or 1), method.parcelas_maximas if method and method.permite_parcelamento else 1))
    total = sum(Decimal(i['quantidade']) * Decimal(i['valor_unitario']) - Decimal(i['desconto']) for i in items)
    data = {'client_id': client.id if client else None, 'client_nome': client.nome if client else cliente_nome.strip().upper(),
            'placa': plate, 'veiculo_descricao': (vehicle.descricao if vehicle else (veiculo_descricao or '').strip().upper()) or None,
            'payment_method_id': method.id if method else None, 'installment_count': installments,
            'employee_id': employee.id if employee else None, 'observacoes': (observacoes or '').strip() or None,
            'items': items}
    if vehicle:
        data['vehicle_id'] = vehicle.id
    card = {'tipo': 'criar_os', 'cliente': data['client_nome'], 'placa': plate, 'veiculo': data['veiculo_descricao'],
            'forma_pagamento': method.nome if method else 'Não definida', 'parcelas': installments,
            'responsavel': employee.nome if employee else None, 'observacoes': data['observacoes'],
            'itens': [{'tipo': i['item_type'], 'catalogo_id': i['reference_id'], 'descricao': i['descricao'], 'quantidade': float(i['quantidade']),
                       'valor_unitario': _money(i['valor_unitario']), 'desconto': _money(i['desconto']),
                       'total': _money(Decimal(i['quantidade']) * Decimal(i['valor_unitario']) - Decimal(i['desconto']))} for i in items],
            'total': _money(total), 'avisos': warnings}
    options = [_options(i['item_type'], found) if found else _alternatives(i['item_type'], i['reference_id'])
               for i, found in zip(items, candidates)]
    # Só os ids das opções vão para a sessão (cookie); nomes e preços vão apenas para o cartão.
    result = _store_draft('criar_os', data, card, opcoes=[[o['id'] for o in opts] for opts in options])
    result['itens'] = [{**item, 'opcoes': opts} for item, opts in zip(card['itens'], options)]
    return result


def propor_alteracao_os(numero: str = '', adicionar_itens: list | None = None, remover_itens: list | None = None,
                        payment_method_id: int | None = None, parcelas: int | None = None,
                        employee_id: int | None = None, observacoes: str | None = None) -> dict:
    order = WorkOrder.query.filter_by(numero=str(numero).strip()).first()
    if not order:
        return {'erro': f'O.S. {numero} não encontrada.'}
    if order.status not in OPEN_STATUSES:
        return {'erro': f'A O.S. {order.numero} está {order.status}; altere pela tela da O.S.'}
    remove = {str(text).strip().upper() for text in (remover_itens or [])}
    current = [{'item_type': i.item_type, 'reference_id': i.reference_id, 'descricao': i.descricao,
                'quantidade': str(i.quantidade), 'valor_unitario': str(i.valor_unitario), 'desconto': str(i.desconto)}
               for i in order.items if i.descricao.upper() not in remove]
    missing = remove - {i.descricao.upper() for i in order.items}
    if missing:
        return {'erro': 'Itens não encontrados na O.S.: ' + ', '.join(sorted(missing)), 'itens_atuais': [i.descricao for i in order.items]}
    try:
        added, warnings, _ = _resolve_items(adicionar_itens)
    except ValueError as exc:
        return {'erro': str(exc)}
    items = current + added
    if not items:
        return {'erro': 'A O.S. ficaria sem itens.'}
    method = db.session.get(PaymentMethod, int(payment_method_id)) if payment_method_id else order.payment_method
    employee = db.session.get(Employee, int(employee_id)) if employee_id else order.employee
    installments = max(1, min(int(parcelas or order.installment_count or 1), method.parcelas_maximas if method and method.permite_parcelamento else 1))
    total = sum(Decimal(i['quantidade']) * Decimal(i['valor_unitario']) - Decimal(i['desconto']) for i in items)
    data = {'work_order_id': order.id, 'version': order.version, 'items': items,
            'payment_method_id': method.id if method else None, 'installment_count': installments,
            'employee_id': employee.id if employee else None,
            'observacoes': order.observacoes if observacoes is None else (observacoes.strip() or None)}
    card = {'tipo': 'alterar_os', 'numero': order.numero, 'cliente': order.client_nome, 'placa': order.placa,
            'removidos': sorted(remove), 'adicionados': [i['descricao'] for i in added],
            'forma_pagamento': method.nome if method else 'Não definida', 'parcelas': installments,
            'responsavel': employee.nome if employee else None,
            'total_antes': _money(order.total_geral), 'total': _money(total), 'avisos': warnings}
    return _store_draft('alterar_os', data, card)


TOOLS = {f.__name__: f for f in (
    buscar_cliente, buscar_veiculo_por_placa, buscar_catalogo, listar_funcionarios, listar_formas_pagamento,
    consultar_os, relatorio_periodo, contas_vencendo, propor_os, propor_alteracao_os)}

_ITEM = {'type': 'object', 'properties': {
    'tipo': {'type': 'string', 'enum': ['SERVICO', 'PECA']},
    'catalogo_id': {'type': 'integer', 'description': 'id vindo de buscar_catalogo; omita se não estiver no catálogo'},
    'descricao': {'type': 'string'},
    'quantidade': {'type': 'number'},
    'valor_unitario': {'type': 'number', 'description': 'só se o usuário disse o preço; senão omita e o preço do catálogo é usado'},
    'desconto': {'type': 'number'}}, 'required': ['tipo', 'descricao']}


def _fn(name, description, properties=None, required=None):
    return {'type': 'function', 'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties or {}, 'required': required or []}}


DECLARATIONS = [
    _fn('buscar_cliente', 'Procura clientes pelo nome (ou placa). Devolve client_id e veículos.', {'texto': {'type': 'string'}}, ['texto']),
    _fn('buscar_veiculo_por_placa', 'Procura veículo e dono pela placa.', {'placa': {'type': 'string'}}, ['placa']),
    _fn('buscar_catalogo', 'Procura serviços ou peças cadastrados e seus preços.',
        {'tipo': {'type': 'string', 'enum': ['SERVICO', 'PECA']}, 'texto': {'type': 'string'}}, ['tipo', 'texto']),
    _fn('listar_funcionarios', 'Lista funcionários ativos (responsáveis pela O.S.).'),
    _fn('listar_formas_pagamento', 'Lista formas de pagamento com ids e parcelas máximas.'),
    _fn('consultar_os', 'Consulta uma O.S. pelo número, ou as últimas por cliente/status.',
        {'numero': {'type': 'string'}, 'cliente': {'type': 'string'},
         'status': {'type': 'string', 'enum': ['ABERTA', 'EM_ANDAMENTO', 'AGUARDANDO_PECA', 'FINALIZADA', 'ENTREGUE', 'CANCELADA']}}),
    _fn('relatorio_periodo', 'Resumo financeiro e de O.S. de um período (datas AAAA-MM-DD). Sem datas: mês atual.',
        {'inicio': {'type': 'string'}, 'fim': {'type': 'string'}}),
    _fn('contas_vencendo', 'Contas a receber ou a pagar em aberto que vencem nos próximos N dias (inclui vencidas).',
        {'tipo': {'type': 'string', 'enum': ['RECEBER', 'PAGAR']}, 'dias': {'type': 'integer'}}),
    _fn('propor_os', 'Monta uma PROPOSTA de nova O.S. para o usuário confirmar. Não grava nada. Pode ser chamada direto com o nome do cliente, a placa e os nomes dos itens: ela localiza cliente, veículo e catálogo sozinha e devolve erro com opções quando houver dúvida.',
        {'client_id': {'type': 'integer'}, 'cliente_nome': {'type': 'string', 'description': 'nome do cliente como o usuário falou'},
         'vehicle_id': {'type': 'integer'}, 'placa': {'type': 'string'}, 'veiculo_descricao': {'type': 'string'},
         'itens': {'type': 'array', 'items': _ITEM}, 'payment_method_id': {'type': 'integer'},
         'parcelas': {'type': 'integer'}, 'employee_id': {'type': 'integer'}, 'observacoes': {'type': 'string'},
         'cliente_novo': {'type': 'boolean', 'description': 'true só se o usuário confirmou que é cliente novo mesmo havendo nomes parecidos'}}, ['itens']),
    _fn('propor_alteracao_os', 'Monta uma PROPOSTA de alteração de uma O.S. aberta para o usuário confirmar. Não grava nada.',
        {'numero': {'type': 'string'}, 'adicionar_itens': {'type': 'array', 'items': _ITEM},
         'remover_itens': {'type': 'array', 'items': {'type': 'string'}, 'description': 'descrições exatas dos itens a remover'},
         'payment_method_id': {'type': 'integer'}, 'parcelas': {'type': 'integer'}, 'employee_id': {'type': 'integer'},
         'observacoes': {'type': 'string'}}, ['numero']),
]


def run_tool(name: str, arguments: dict) -> dict:
    tool = TOOLS.get(name)
    if not tool:
        return {'erro': f'Ferramenta desconhecida: {name}'}
    try:
        return tool(**(arguments or {}))
    except TypeError as exc:
        return {'erro': f'Argumentos inválidos para {name}: {exc}'}
    except ValueError as exc:
        return {'erro': str(exc)}
