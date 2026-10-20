"""Parse complete financial exports without applying historical balance movements."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import re

from .readers import read_table
from .service import normalize


def money(value):
    cleaned = str(value or '0').replace('R$', '').replace('\xa0', '').replace(' ', '')
    if ',' in cleaned:
        cleaned = cleaned.replace('.', '').replace(',', '.')
    try:
        number = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError('Valor monetário inválido.') from exc
    if not number.is_finite() or abs(number) >= Decimal('10000000000') or number.as_tuple().exponent < -2:
        raise ValueError('Valor monetário fora dos limites.')
    return number


def source_date(value, timestamp=False):
    if not value or value.strip() in ('-', '--'):
        return None
    for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            result = datetime.strptime(value.strip(), fmt)
            return result if timestamp else result.date()
        except ValueError:
            continue
    raise ValueError('Data de origem inválida: ' + value)


def parse_finance_export(path, kind):
    if kind not in ('PAGAR', 'RECEBER'):
        raise ValueError('Tipo financeiro inválido.')
    headers = None
    result = []
    for number, values in read_table(path, dict(encoding='utf-8-sig', delimiter='auto', table=0, header_row=1)):
        if number == 0:
            headers = values
            continue
        row = {normalize(h): values[i].strip() if i < len(values) else '' for i, h in enumerate(headers)}
        state = normalize(re.sub(r'\(.*\)', '', row.get('situacao', '')))
        if state in ('pago', 'recebido', 'liquidado'):
            status = 'PAGO' if kind == 'PAGAR' else 'RECEBIDO'
        elif state in ('emaberto', 'ematraso', 'pendente'):
            status = 'PENDENTE'
        else:
            raise ValueError(f'Linha {number}: situação não reconhecida.')
        due = source_date(row.get('vencimento'))
        if due is None:
            raise ValueError(f'Linha {number}: vencimento ausente.')
        settlement = source_date(row.get('datadeliquidacao'))
        if settlement is None:
            match = re.search(r'\((\d{2}/\d{2}/\d{4})\)', row.get('situacao', ''))
            settlement = source_date(match.group(1)) if match else None
        if status != 'PENDENTE' and settlement is None:
            raise ValueError(f'Linha {number}: liquidação ausente em título pago.')
        created = source_date(row.get('datadecadastro'), timestamp=True)
        updated = source_date(row.get('datadealteracao'), timestamp=True)
        issued = source_date(row.get('emissao')) or (created.date() if created else due)
        title = row.get('nomedareceita') or row.get('nomedadespesa') or row.get('cliente') or row.get('fornecedor')
        if not title or len(title) > 255 or len(row.get('categoria', '')) > 80:
            raise ValueError(f'Linha {number}: descrição/categoria inválida.')
        payload = dict(entry_type=kind, descricao=title, categoria=row.get('categoria') or None,
            valor=money(row.get('valororiginal')), vencimento=due, issued_on=issued, competence_on=issued,
            payment_receipt_at=settlement, status=status,
            valor_baixa=money(row.get('valorbaixado')), juros=money(row.get('juros')),
            acrescimo=money(row.get('acrescimo')), desconto=money(row.get('desconto')), taxa=money(row.get('taxa')),
            observacoes_pagamento=json.dumps(dict(zip(headers, values)), ensure_ascii=False),
            reference_type='MIGRACAO_FINANCEIRO', reference_id=None,
            installment_number=1, installment_total=1, payment_method_id=None, bank_account_id=None)
        if created:
            payload['created_at'] = created
        if updated:
            payload['updated_at'] = updated
        result.append(dict(payload=payload, method=row.get('formadepagamento', ''), account=row.get('contabancaria', ''),
            net=money(row.get('valorrecebido') if kind == 'RECEBER' else row.get('valorpago'))))
    if not result:
        raise ValueError('Exportação sem registros.')
    return result
