"""Explicitly linked summary/item tables from detailed legacy OS exports."""
from collections import Counter
from decimal import Decimal
import json

from bs4 import BeautifulSoup
from sqlalchemy import select

from ..models import db, WorkOrder, WorkOrderItem, WorkOrderStatusHistory
from ..operations.models import AuditEvent
from .models import DataMigration
from .service import (convert, suggest_mapping, normalize, parse_decimal,
                      resolve_work_orders, migration_fallback_client)


def read_detailed_orders(path):
    with open(path, 'rb') as stream:
        soup = BeautifulSoup(stream, 'lxml')
    headers = None
    orders = {}
    for tr in soup.find_all('tr'):
        cells = tr.find_all(['td', 'th'], recursive=False)
        if len(cells) != 15:
            continue
        values = [cell.get_text(' ', strip=True) for cell in cells]
        if normalize(values[0]) == 'os':
            headers = values
            continue
        if not headers or not values[0].isdigit():
            continue
        if values[0] in orders:
            raise ValueError('OS repetida na exportação: ' + values[0])
        items = []
        table = soup.find('table', attrs={'data-parent': tr.get('data-id'), 'data-subtable': 'true'})
        if table:
            for item_row in table.find_all('tr'):
                item_cells = item_row.find_all('td', recursive=False)
                if len(item_cells) != 6:
                    continue
                row = [cell.get_text(' ', strip=True) for cell in item_cells]
                if normalize(row[5]) in ('sim', 's', '1'):
                    continue
                if normalize(row[5]) not in ('nao', 'n', '0', ''):
                    raise ValueError('Situação de item desconhecida na OS ' + values[0])
                kind = {'produto': 'PECA', 'servico': 'SERVICO'}.get(normalize(row[1]))
                if not kind or not row[0] or len(row[0]) > 255:
                    raise ValueError('Item inválido na OS ' + values[0])
                qty, unit, total = (parse_decimal(row[i]) for i in (2, 3, 4))
                if qty <= 0 or total > qty * unit:
                    raise ValueError('Quantidade ou total inválido na OS ' + values[0])
                items.append(dict(item_type=kind, descricao=row[0], quantidade=qty,
                    valor_unitario=unit, desconto=qty * unit - total, total=total))
        orders[values[0]] = {'values': values, 'items': items, 'detailed': table is not None}
    if not orders:
        raise ValueError('Nenhuma OS encontrada.')
    return headers, orders


def item_key(item):
    return tuple(str(item[key]) for key in ('item_type', 'descricao')) + tuple(
        Decimal(item[key]) for key in ('quantidade', 'valor_unitario', 'desconto', 'total'))


def complete_orders(path, apply=False):
    headers, source = read_detailed_orders(path)
    mapping = suggest_mapping('ordens_servico', headers)
    migration = DataMigration(entity='ordens_servico', headers_json=json.dumps(headers))
    candidates = [(number, convert(migration, row['values'], mapping), '') for number, row in source.items()]
    errors = []
    fallback = migration_fallback_client() if apply else (None, 'Cliente VHSys (Importado)')
    resolved = {number: data for number, data, _ in resolve_work_orders(candidates, errors, fallback)}
    if errors:
        raise ValueError('Não foi possível resolver todas as OS.')
    query = select(WorkOrder).where(WorkOrder.numero.in_(source))
    if apply:
        query = query.with_for_update()
    existing = {order.numero: order for order in db.session.scalars(query)}
    report = []
    for number, row in source.items():
        data = resolved[number]
        order = existing.get(number)
        items = row['items']
        current = list(order.items) if order else []
        count = Counter(item_key({k: getattr(item, k) for k in WorkOrderItem.__table__.columns.keys()}) for item in current)
        missing = []
        for item in items:
            key = item_key(item)
            if count[key]:
                count[key] -= 1
            else:
                missing.append(item)
        if current and any(count.values()):
            # Some previous imports allocated an order-level discount to one item.
            base_keys = lambda values: Counter((i['item_type'], i['descricao'], Decimal(i['quantidade']), Decimal(i['valor_unitario'])) for i in values)
            current_dicts = [{k: getattr(i, k) for k in WorkOrderItem.__table__.columns.keys()} for i in current]
            if base_keys(current_dicts) == base_keys(items) and sum(i.total for i in current) == data['total_geral']:
                missing = []
            else:
                report.append(dict(os=number, status='VALORES_EXISTENTES_PRESERVADOS', added=0))
                continue
        changes = {}
        if order:
            for field in ('client_nome', 'placa', 'veiculo_descricao', 'observacoes', 'employee_id'):
                if not getattr(order, field) and data.get(field):
                    changes[field] = data[field]
            if missing:
                for field in ('total_servicos', 'total_pecas', 'total_geral'):
                    if getattr(order, field) != data[field]:
                        changes[field] = data[field]
        status = 'NOVA' if not order else 'COMPLETADA' if missing or changes else 'JA_COMPLETA'
        if apply and status != 'JA_COMPLETA':
            before = {field: getattr(order, field) for field in changes} if order else None
            if not order:
                order = WorkOrder(**{k: v for k, v in data.items() if k in WorkOrder.__table__.columns})
                db.session.add(order)
                db.session.flush()
                db.session.add(WorkOrderStatusHistory(work_order_id=order.id, status=order.status,
                    observation='Importada de exportação detalhada.'))
            else:
                for field, value in changes.items():
                    setattr(order, field, value)
            added = []
            for item in missing:
                record = WorkOrderItem(work_order_id=order.id, **item)
                db.session.add(record)
                db.session.flush()
                added.append(record.id)
            db.session.add(AuditEvent(action='MIGRACAO_COMPLETAR_OS', entity_type='WorkOrder', entity_id=order.id,
                details=json.dumps({'before': before, 'added_item_ids': added}, default=str)))
        report.append(dict(os=number, status=status, added=len(missing), source_items=len(items), changes=list(changes)))
    return report
