"""Recover payment methods from receivables explicitly referencing an OS."""
from collections import defaultdict
from decimal import Decimal
import json
import re

from sqlalchemy import select

from ..models import db, WorkOrder, WorkOrderPayment, PaymentMethod
from ..operations.models import AuditEvent
from .readers import read_table
from .service import normalize, parse_decimal, PLATE_PATTERN, normalize_plate


def reconcile_os_payments(path, apply=False):
    groups = defaultdict(list)
    headers = None
    for number, row in read_table(path, dict(encoding='utf-8-sig', delimiter='auto', table=0, header_row=1)):
        if not number:
            headers = {normalize(name): i for i, name in enumerate(row)}
            if not {'nomedareceita', 'formadepagamento', 'valororiginal'} <= headers.keys():
                raise ValueError('São necessárias as colunas Nome da Receita, Forma de Pagamento e Valor Original.')
            continue
        def cell(name):
            index = headers.get(name)
            return row[index].strip() if index is not None and index < len(row) else ''
        reference = normalize(cell('nomedareceita'))
        match = re.fullmatch(r'(?:ordemdeservico|os)(\d+)', reference)
        if not match:
            continue
        groups[match[1]].append((cell('formadepagamento'), parse_decimal(cell('valororiginal')), cell('cliente')))
    methods = defaultdict(list)
    for method in db.session.scalars(select(PaymentMethod).where(PaymentMethod.ativo.is_(True))):
        methods[normalize(method.nome)].append(method)
    query = select(WorkOrder).where(WorkOrder.numero.in_(groups)).order_by(WorkOrder.id)
    if apply:
        query = query.with_for_update()
    orders = {order.numero: order for order in db.session.scalars(query)}
    report = []
    for number, rows in groups.items():
        order = orders.get(number)
        reason = None
        allocations = defaultdict(lambda: Decimal('0'))
        for name, value, customer in rows:
            matches = methods[normalize(name)]
            if len(matches) != 1 or value <= 0:
                reason = 'Forma de pagamento desconhecida/ambígua ou valor inválido.'
                break
            allocations[matches[0].id] += value
            plates = {normalize_plate(m.group()) for m in PLATE_PATTERN.finditer(customer)}
            if order and order.placa and plates and plates != {normalize_plate(order.placa)}:
                reason = 'Placa do financeiro diverge da OS.'
        if not order:
            reason = 'OS não encontrada.'
        elif sum(allocations.values()) != order.total_geral:
            reason = reason or 'Soma do financeiro difere do total da OS.'
        if reason:
            report.append({'os': number, 'status': 'PENDENCIA', 'motivo': reason})
            continue
        existing = list(order.payments)
        expected_method = next(iter(allocations)) if len(allocations) == 1 else None
        current_allocations = defaultdict(lambda: Decimal('0'))
        for payment in existing:
            current_allocations[payment.payment_method_id] += payment.valor
        same = (not existing and order.payment_method_id == expected_method and expected_method is not None) or (
            bool(existing) and current_allocations == allocations)
        if same:
            report.append({'os': number, 'status': 'JA_PREENCHIDA'})
            continue
        if existing or order.payment_method_id is not None:
            report.append({'os': number, 'status': 'PENDENCIA', 'motivo': 'OS já possui outro pagamento; revisar conflito.'})
            continue
        if apply:
            before = {'payment_method_id': order.payment_method_id, 'payments': []}
            order.payment_method_id = expected_method
            if len(allocations) > 1:
                for method_id, value in allocations.items():
                    db.session.add(WorkOrderPayment(work_order_id=order.id, payment_method_id=method_id,
                        valor=value, installment_count=1))
            db.session.add(AuditEvent(action='MIGRACAO_PAGAMENTO_OS', entity_type='WorkOrder', entity_id=order.id,
                details=json.dumps({'before': before, 'allocations': {str(k): str(v) for k, v in allocations.items()}})))
        report.append({'os': number, 'status': 'ATUALIZADA' if apply else 'PRONTA', 'formas': len(allocations)})
    return report
