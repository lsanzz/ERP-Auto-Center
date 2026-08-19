from __future__ import annotations

import json
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from .utils import parse_decimal


class _ReportParser(HTMLParser):
    """Extrai tabelas sem depender de BeautifulSoup ou de um navegador."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[dict[str, Any]] = []
        self._table_stack: list[dict[str, Any]] = []
        self._row_stack: list[dict[str, Any]] = []
        self._cell: dict[str, Any] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table':
            table = {'attrs': attrs, 'headers': [], 'rows': []}
            self._table_stack.append(table)
            self.tables.append(table)
        elif tag == 'tr' and self._table_stack:
            self._row_stack.append({'cells': [], 'table': self._table_stack[-1]})
        elif tag in ('th', 'td') and self._row_stack and self._cell is None:
            self._cell = {'tag': tag, 'field': attrs.get('data-field'), 'text': []}

    def handle_endtag(self, tag):
        if tag in ('th', 'td') and self._cell is not None:
            text = ' '.join(''.join(self._cell['text']).split())
            self._row_stack[-1]['cells'].append((self._cell['tag'], self._cell['field'], text))
            self._cell = None
        elif tag == 'tr' and self._row_stack:
            row = self._row_stack.pop()
            table = row['table']
            cells = row['cells']
            if any(cell[0] == 'th' for cell in cells):
                table['headers'] = [field or text for _, field, text in cells]
            elif cells:
                table['rows'].append([text for _, _, text in cells])
        elif tag == 'table' and self._table_stack:
            self._table_stack.pop()

    def handle_data(self, data):
        if self._cell is not None:
            self._cell['text'].append(data)


def _parse_money(value: str) -> float:
    return float(parse_decimal(re.sub(r'[^0-9,.-]', '', value or '0')))


def _parse_br_date(value: str) -> str | None:
    try:
        return datetime.strptime(value.strip(), '%d/%m/%Y').date().isoformat()
    except (TypeError, ValueError):
        return None


def _table_with_headers(tables, expected: set[str]):
    for table in tables:
        headers = {str(header).lower() for header in table['headers']}
        if {value.lower() for value in expected}.issubset(headers):
            return table
    return None


def parse_legacy_reports(entrada_html: bytes, ordem_servico_html: bytes) -> dict[str, list[dict[str, Any]]]:
    """Converte os relatórios HTML do VHSYS para o formato do importador atual."""
    entrada_text = entrada_html.decode('utf-8', errors='replace')
    os_text = ordem_servico_html.decode('utf-8', errors='replace')
    entrada_parser = _ReportParser()
    entrada_parser.feed(entrada_text)
    os_parser = _ReportParser()
    os_parser.feed(os_text)

    entrada_table = _table_with_headers(entrada_parser.tables, {'Entrada', 'Fornecedor', 'ValorTotal', 'DataPedido'})
    os_table = _table_with_headers(os_parser.tables, {'OS', 'Cliente', 'ValorTotal', 'DataPedido'})
    if not entrada_table:
        raise ValueError('Não encontrei a tabela principal de entradas de mercadoria no HTML.')
    if not os_table:
        raise ValueError('Não encontrei a tabela principal de ordens de serviço no HTML.')

    def row_dict(table, row):
        return {str(header): row[index] if index < len(row) else '' for index, header in enumerate(table['headers'])}

    financial_entries = []
    for row in entrada_table['rows']:
        item = row_dict(entrada_table, row)
        number = item.get('Entrada', '').strip()
        supplier = item.get('Fornecedor', '').strip()
        if not number or not supplier:
            continue
        financial_entries.append({
            'entry_type': 'PAGAR',
            'descricao': f'Entrada {number} - {supplier}',
            'categoria': 'Compras / entrada de mercadoria',
            'valor': _parse_money(item.get('ValorTotal', '0')),
            'vencimento': _parse_br_date(item.get('DataPedido', '')),
            'status': 'PENDENTE',
            'reference_type': 'ENTRADA_ANTIGA',
            'reference_id': number,
        })

    # As tabelas de itens ficam logo abaixo de cada linha principal e possuem
    # data-parent igual ao id da O.S. no relatório.
    item_tables = [table for table in os_parser.tables if {'Tipo', 'Qtde', 'ValorUnit', 'ValorTotal'}.issubset({str(h) for h in table['headers']})]
    items_by_parent = {}
    for table in item_tables:
        parent = table['attrs'].get('data-parent')
        if parent:
            items_by_parent[str(parent)] = [row_dict(table, row) for row in table['rows']]

    work_orders = []
    receivables = []
    plate_pattern = re.compile(r'\b[A-Z]{3}[- ]?[0-9A-Z]{4}\b', re.I)
    for row_position, row in enumerate(os_table['rows']):
        item = row_dict(os_table, row)
        number = item.get('OS', '').strip()
        client_vehicle = item.get('Cliente', '').strip()
        if not number or not client_vehicle:
            continue
        plate_match = plate_pattern.search(client_vehicle)
        placa = plate_match.group(0).replace(' ', '-').upper() if plate_match else None
        client_name = client_vehicle[:plate_match.start()].strip() if plate_match else client_vehicle
        vehicle = client_vehicle[plate_match.end():].strip(' -') if plate_match else None
        if plate_match and not vehicle:
            # O relatório costuma trazer CLIENTE + veículo + placa; preserva o
            # texto completo como cliente quando não for possível separar.
            vehicle = client_vehicle
        # data-id está no HTML, mas não é necessário para importar os itens;
        # a ordem das tabelas detalhadas coincide com a ordem das linhas.
        detail_rows = item_tables[row_position]['rows'] if row_position < len(item_tables) else []
        items = []
        for detail in detail_rows:
            detail_item = row_dict(item_tables[row_position], detail)
            kind = 'PECA' if detail_item.get('Tipo', '').lower().startswith('prod') else 'SERVICO'
            items.append({
                'item_type': kind,
                'descricao': detail_item.get('', '').strip() or 'Item importado',
                'quantidade': _parse_money(detail_item.get('Qtde', '1')),
                'valor_unitario': _parse_money(detail_item.get('ValorUnit', '0')),
                'total': _parse_money(detail_item.get('ValorTotal', '0')),
            })
        work_orders.append({
            'numero': number,
            'client_nome': client_name or client_vehicle,
            'placa': placa,
            'veiculo_descricao': vehicle,
            'data_entrada': _parse_br_date(item.get('DataPedido', '')),
            'status': 'FINALIZADA',
            'emitir_nota': False,
            'items': items,
        })
        receivables.append({
            'entry_type': 'RECEBER',
            'descricao': f'O.S. {number} - {client_name or client_vehicle}',
            'categoria': 'Serviços / O.S. migrada',
            'valor': _parse_money(item.get('ValorTotal', '0')),
            'vencimento': _parse_br_date(item.get('DataPedido', '')),
            'status': 'PENDENTE',
            'reference_type': 'OS_NUMERO',
            'reference_id': number,
        })

    if not work_orders and not financial_entries:
        raise ValueError('Os HTMLs não possuem registros importáveis.')
    return {'work_orders': work_orders, 'financial_entries': financial_entries + receivables}


def serialize_legacy_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
