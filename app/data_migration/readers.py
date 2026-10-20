"""Bounded readers. HTML is parsed as data, never rendered or executed."""
import csv
import json
from collections import deque
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from zipfile import ZipFile

MAX_COLUMNS = 150
MAX_CELL = 16000
MAX_ROWS = 500000


def text_cell(value):
    if value is None:
        return ''
    if isinstance(value, (date, datetime)):
        return value.strftime('%Y-%m-%d')
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


class TableReader(HTMLParser):
    def __init__(self, table):
        super().__init__(convert_charrefs=True)
        self.target = table
        self.table = 0
        self.depth = 0
        self.target_depth = None
        self.row = None
        self.cell = None
        self.span = 1
        self.ready = deque()
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.table += 1
            self.depth += 1
            if self.table == self.target:
                self.target_depth = self.depth
        if self.target_depth is None or self.depth != self.target_depth:
            return
        if tag in ('script', 'style'):
            self.hidden += 1
        elif tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = ''
            attributes = dict(attrs)
            try:
                self.span = int(attributes.get('colspan', 1))
                rowspan = int(attributes.get('rowspan', 1))
            except ValueError:
                raise ValueError('Tabela HTML com células mescladas inválidas.')
            if not 1 <= self.span <= MAX_COLUMNS or rowspan != 1:
                raise ValueError('Exporte uma tabela sem mesclagem vertical (rowspan).')
        elif tag == 'br' and self.cell is not None:
            self.cell += ' '

    def handle_data(self, data):
        if self.cell is not None and not self.hidden and self.depth == self.target_depth:
            self.cell += data
            if len(self.cell) > MAX_CELL:
                raise ValueError('Uma célula excede o limite de 16.000 caracteres.')

    def handle_endtag(self, tag):
        if self.target_depth is not None and self.depth == self.target_depth:
            if tag in ('script', 'style'):
                self.hidden = max(0, self.hidden - 1)
            elif tag in ('td', 'th') and self.cell is not None:
                self.row.extend([self.cell.strip()] + [''] * (self.span - 1))
                self.cell = None
                if len(self.row) > MAX_COLUMNS:
                    raise ValueError('A tabela excede 150 colunas.')
            elif tag == 'tr' and self.row is not None:
                self.ready.append(self.row)
                self.row = None
        if tag == 'table':
            if self.target_depth == self.depth:
                self.target_depth = None
            self.depth = max(0, self.depth - 1)


class TableStats(HTMLParser):
    """Find the most substantial leaf table without retaining its contents."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.count = 0
        self.stack = []
        self.rows = {}
        self.max_columns = {}
        self.current_columns = {}

    def handle_starttag(self, tag, _attrs):
        if tag == 'table':
            self.count += 1
            self.stack.append(self.count)
            self.rows[self.count] = 0
            self.max_columns[self.count] = 0
        elif tag == 'tr' and self.stack:
            table = self.stack[-1]
            self.rows[table] += 1
            self.current_columns[table] = 0
        elif tag in ('td', 'th') and self.stack:
            table = self.stack[-1]
            self.current_columns[table] = self.current_columns.get(table, 0) + 1
            self.max_columns[table] = max(self.max_columns[table], self.current_columns[table])

    def handle_endtag(self, tag):
        if tag == 'table' and self.stack:
            self.stack.pop()

    def best(self):
        candidates = [number for number, rows in self.rows.items() if rows >= 2]
        if not candidates:
            return 1
        return max(candidates, key=lambda number: (self.rows[number] * self.max_columns[number], self.rows[number]))


def detect_html_table(path, encoding):
    parser = TableStats()
    with open(path, encoding=encoding, newline='') as stream:
        while chunk := stream.read(65536):
            parser.feed(chunk)
    parser.close()
    return parser.best()


def raw_rows(path, options):
    suffix = Path(path).suffix.lower()
    with open(path, 'rb') as stream:
        prefix = stream.read(4096)
    probe = prefix.decode('utf-16' if prefix.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig', errors='ignore').lstrip().lower()
    html_like = suffix in ('.html', '.htm') or (suffix == '.xls' and any(tag in probe for tag in ('<html', '<table', '<!doctype html')))
    if suffix == '.xlsx':
        # Bound decompressed input, including shared strings loaded by openpyxl.
        with ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > 256 * 1024 * 1024:
                raise ValueError('Planilha descompactada excede 256 MB. Divida o arquivo.')
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            sheet_number = max(1, options['table']) - 1
            if sheet_number >= len(workbook.worksheets):
                raise ValueError('A aba informada não existe na planilha.')
            sheet = workbook.worksheets[sheet_number]
            # Ignore inaccurate dimensions emitted by third-party exporters.
            sheet.reset_dimensions()
            for row in sheet.iter_rows(values_only=True):
                yield row
        finally:
            workbook.close()
        return
    if suffix == '.xls' and not html_like:
        import xlrd
        workbook = xlrd.open_workbook(path, on_demand=True)
        try:
            sheet_number = max(1, options['table']) - 1
            if sheet_number >= workbook.nsheets:
                raise ValueError('A aba informada não existe na planilha.')
            sheet = workbook.sheet_by_index(sheet_number)
            for row_number in range(sheet.nrows):
                values = []
                for cell in sheet.row(row_number):
                    value = cell.value
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        parts = xlrd.xldate_as_tuple(value, workbook.datemode)
                        value = datetime(*parts).date() if parts[3:] == (0, 0, 0) else datetime(*parts)
                    values.append(value)
                yield values
        finally:
            workbook.release_resources()
        return
    encoding = options['encoding']
    if prefix.startswith((b'\xff\xfe', b'\xfe\xff')):
        encoding = 'utf-16'
    with open(path, encoding=encoding, newline='') as stream:
        if html_like:
            parser = TableReader(options['table'] or detect_html_table(path, encoding))
            while chunk := stream.read(65536):
                parser.feed(chunk)
                while parser.ready:
                    yield parser.ready.popleft()
            parser.close()
            while parser.ready:
                yield parser.ready.popleft()
        else:
            delimiter = options['delimiter']
            if delimiter == 'auto':
                sample = stream.read(32768)
                stream.seek(0)
                try:
                    delimiter = csv.Sniffer().sniff(sample, delimiters=',;\t|').delimiter
                except csv.Error:
                    delimiter = '\t' if suffix == '.tsv' else ';'
            yield from csv.reader(stream, delimiter=delimiter)


def read_table(path, options):
    """Yield header and rows; keep source record numbers (multiline CSV = one record)."""
    header = None
    for number, raw in enumerate(raw_rows(path, options), 1):
        if number < options['header_row']:
            continue
        if number > MAX_ROWS + options['header_row']:
            raise ValueError('Limite de 500.000 registros por arquivo. Divida a exportação.')
        row = [text_cell(cell) for cell in raw]
        while row and not row[-1]:
            row.pop()
        if not any(row):
            continue
        if len(row) > MAX_COLUMNS or any(len(cell) > MAX_CELL for cell in row):
            raise ValueError('Limite excedido: 150 colunas ou 16.000 caracteres por célula.')
        if len(json.dumps(row, ensure_ascii=False).encode('utf-8')) > 60000:
            raise ValueError('Um registro excede 60 KB. Reduza o conteúdo dos campos de texto.')
        if header is None:
            header = [cell or f'Coluna {i + 1}' for i, cell in enumerate(row)]
            yield 0, header
        else:
            yield number, row
    if header is None:
        raise ValueError('Nenhuma tabela encontrada. Confira a aba/tabela e a linha do cabeçalho.')
