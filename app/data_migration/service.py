import hashlib
import csv
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import BadZipFile
from defusedxml.ElementTree import ParseError

try:
    from defusedxml.common import DefusedXmlException
except ImportError:  # App startup must still allow dependency installation/migrations.
    class DefusedXmlException(Exception):
        pass
try:
    from openpyxl.utils.exceptions import InvalidFileException
except ImportError:
    class InvalidFileException(Exception):
        pass
try:
    from xlrd.biffh import XLRDError
except ImportError:
    class XLRDError(Exception):
        pass

from flask import current_app
from sqlalchemy import bindparam, func, insert, select, update
from sqlalchemy.exc import IntegrityError, DataError

from ..models import (Client, Employee, Supplier, Product, Service, FinancialEntry,
                      WorkOrder, WorkOrderStatusHistory, PaymentMethod, db)
from ..fleet.models import Vehicle
from ..operations.models import AuditEvent, InventoryMovement
from ..jobs import enqueue
from .models import DataMigration, MigrationRow, MigrationKey
from .readers import read_table

BATCH_SIZE = 500
# field: label; only explicit, supported fields may be written.
CONTACT = {'nome': 'Nome', 'telefone': 'Telefone', 'email': 'E-mail', 'endereco': 'Endereço',
           'inscricao_estadual': 'Inscrição estadual', 'observacoes': 'Observações'}
SCHEMAS = {
    'clientes': (Client, 'Clientes', {**CONTACT, 'cpf_cnpj': 'CPF / CNPJ'}, ['nome']),
    'fornecedores': (Supplier, 'Fornecedores', {**CONTACT, 'cnpj_cpf': 'CPF / CNPJ', 'razao_social': 'Razão social'}, ['nome']),
    'produtos': (Product, 'Produtos e estoque inicial', {'codigo': 'Código', 'nome': 'Nome', 'categoria': 'Categoria',
        'marca': 'Marca', 'unidade': 'Unidade', 'ncm': 'NCM', 'cfop': 'CFOP', 'custo': 'Custo',
        'preco_venda': 'Preço de venda', 'estoque_atual': 'Estoque inicial', 'estoque_minimo': 'Estoque mínimo'}, ['codigo', 'nome']),
    'servicos': (Service, 'Serviços', {'nome': 'Nome', 'descricao': 'Descrição', 'preco_base': 'Preço base'}, ['nome']),
    'veiculos': (Vehicle, 'Veículos', {'cliente_documento': 'CPF / CNPJ do cliente', 'placa': 'Placa',
        'descricao': 'Descrição', 'marca': 'Marca', 'modelo': 'Modelo', 'ano_fabricacao': 'Ano de fabricação',
        'ano_modelo': 'Ano do modelo', 'chassi': 'Chassi', 'renavam': 'Renavam', 'cor': 'Cor',
        'quilometragem': 'Quilometragem', 'observacoes': 'Observações'}, ['cliente_documento', 'placa', 'descricao']),
    'ordens_servico': (WorkOrder, 'Ordens de serviço', {
        'numero': 'Número da OS', 'cliente_documento': 'CPF / CNPJ do cliente',
        'cliente_nome': 'Nome do cliente', 'cliente_veiculo': 'Cliente, veículo e placa',
        'placa': 'Placa', 'veiculo_descricao': 'Descrição do veículo', 'vendedor': 'Vendedor / responsável',
        'total_servicos': 'Valor dos serviços', 'total_pecas': 'Valor dos produtos',
        'total_geral': 'Valor total', 'installment_count': 'Total de parcelas',
        'forma_pagamento': 'Forma de pagamento',
        'data_entrada': 'Data da OS', 'status_origem': 'Situação', 'observacoes': 'Observações'},
        ['numero', 'data_entrada']),
}
for kind, label in [('pagar', 'Contas a pagar'), ('receber', 'Contas a receber')]:
    SCHEMAS[kind] = (FinancialEntry, label, {'origem_id': 'Identificador único na origem', 'descricao': 'Descrição',
        'contraparte': 'Cliente / fornecedor', 'categoria': 'Categoria', 'valor': 'Valor', 'vencimento': 'Vencimento',
        'issued_on': 'Data de emissão', 'competence_on': 'Competência', 'forma_pagamento': 'Forma de pagamento'}, ['valor', 'vencimento'])


def normalize(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode().lower())


def suggest_mapping(entity, headers):
    aliases = {'nome': ['nomefantasia', 'cliente', 'fornecedor', 'produto', 'servico', 'razaosocial'],
        'cpf_cnpj': ['cpf', 'cnpj', 'documento', 'cnpjcpf'], 'cnpj_cpf': ['cpf', 'cnpj', 'documento', 'cpfcnpj'],
        'codigo': ['cod', 'sku', 'codigoproduto'], 'telefone': ['fone', 'celular'],
        'preco_venda': ['precovenda', 'preco', 'valorvenda'], 'estoque_atual': ['estoque', 'saldo', 'quantidade'],
        'origem_id': ['id', 'codigo', 'numero', 'cod', 'iddocumento'], 'vencimento': ['datavencimento', 'vencto'],
        'issued_on': ['emissao', 'dataemissao'], 'competence_on': ['competencia'],
        'descricao': ['nomedareceita', 'nomedadespesa', 'receita', 'despesa', 'historico'],
        'contraparte': ['cliente', 'fornecedor', 'sacado', 'favorecido'],
        'valor': ['valororiginal', 'valortitulo', 'valordocumento']}
    aliases.update({'numero': ['os', 'ordem', 'numeroos'], 'cliente_veiculo': ['cliente'],
        'vendedor': ['responsavel', 'mecanico'], 'total_servicos': ['valorservicos'],
        'total_pecas': ['valorprodutos', 'valorpecas'], 'total_geral': ['valortotal'],
        'installment_count': ['totaldeparcelas', 'parcelas'], 'data_entrada': ['datadaos', 'dataos', 'datapedido'],
        'status_origem': ['situacao', 'status'],
        'forma_pagamento': ['pagamento', 'meiodepagamento', 'paymentmethod', 'formadepagamento']})
    result = {}
    used = set()
    for field, label in SCHEMAS[entity][2].items():
        candidates = [normalize(field), normalize(label)] + aliases.get(field, [])
        for i, header in enumerate(headers):
            if i not in used and normalize(header) in candidates:
                result[field] = i
                used.add(i)
                break
    return result


def storage_path(migration):
    root = Path(current_app.config.get('MIGRATION_STORAGE') or Path(current_app.instance_path) / 'data_migrations')
    root.mkdir(parents=True, exist_ok=True)
    return root / migration.storage_name


def prepare(migration_id):
    try:
        _prepare(migration_id)
    except UnicodeError as exc:
        raise ValueError('Não foi possível decodificar o arquivo. Tente Windows-1252 ou Latin-1 nas opções de leitura.') from exc
    except ModuleNotFoundError as exc:
        raise ValueError('Falta uma dependência para ler esta planilha. Execute: python -m pip install -r requirements.txt') from exc
    except (BadZipFile, InvalidFileException, XLRDError, ParseError, DefusedXmlException, csv.Error) as exc:
        raise ValueError('Arquivo inválido ou corrompido. Exporte novamente e confira o formato e o separador.') from exc


def _prepare(migration_id):
    migration = db.session.get(DataMigration, migration_id)
    if not migration or migration.status != 'PREPARANDO':
        return
    last_number = db.session.scalar(select(func.max(MigrationRow.number)).where(MigrationRow.migration_id == migration.id)) or 0
    buffer = []
    for number, values in read_table(storage_path(migration), json.loads(migration.options_json)):
        if not number:
            migration.headers_json = json.dumps(values, ensure_ascii=False)
            migration.mapping_json = json.dumps(suggest_mapping(migration.entity, values))
        elif number > last_number:
            buffer.append({'migration_id': migration.id, 'number': number, 'payload': json.dumps(values, ensure_ascii=False)})
        if len(buffer) >= BATCH_SIZE:
            db.session.execute(insert(MigrationRow), buffer)
            migration.total += len(buffer)
            db.session.commit()
            buffer.clear()
    if buffer:
        db.session.execute(insert(MigrationRow), buffer)
        migration.total += len(buffer)
    if not migration.total:
        raise ValueError('O arquivo tem cabeçalho, mas não contém registros para importar.')
    migration.status = 'PREVIA'


def parse_decimal(value):
    value = value.replace('R$', '').replace(' ', '').replace('\u00a0', '')
    if ',' in value:
        value = value.replace('.', '').replace(',', '.')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError('Número inválido. Use 1234,56 ou 1234.56.')
    if not number.is_finite() or number < 0 or number >= Decimal('10000000000'):
        raise ValueError('O número deve ser positivo ou zero e menor que 10 bilhões.')
    if number.as_tuple().exponent < -2:
        raise ValueError('Use no máximo duas casas decimais.')
    return number


def parse_date(value):
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError('Data inválida. Use DD/MM/AAAA ou AAAA-MM-DD.')


def convert(migration, values, mapping):
    model, _, fields, required = SCHEMAS[migration.entity]
    headers = json.loads(migration.headers_json)
    if len(values) > len(headers):
        raise ValueError('Há mais células que colunas no cabeçalho. Confira o separador.')
    data = {}
    for field in fields:
        index = mapping.get(field)
        value = values[index].strip() if isinstance(index, int) and index < len(values) else ''
        if not value:
            if field in required:
                raise ValueError(f'{fields[field]}: campo obrigatório vazio.')
            continue
        try:
            if field in ('origem_id', 'cliente_documento', 'cliente_nome', 'cliente_veiculo', 'vendedor', 'status_origem', 'forma_pagamento', 'contraparte'):
                if len(value) > 120:
                    raise ValueError('Máximo de 120 caracteres.')
            else:
                column = model.__table__.columns[field]
                if isinstance(column.type, db.Numeric):
                    value = parse_decimal(value)
                elif isinstance(column.type, db.Date):
                    value = parse_date(value)
                elif isinstance(column.type, db.Integer):
                    if not re.fullmatch(r'\d{1,9}', value):
                        raise ValueError('Use um inteiro positivo ou zero.')
                    value = int(value)
                    if field.startswith('ano_') and not 1886 <= value <= 2100:
                        raise ValueError('Ano fora do intervalo 1886–2100.')
                elif getattr(column.type, 'length', None) and len(value) > column.type.length:
                    raise ValueError(f'Máximo de {column.type.length} caracteres.')
            if field in ('cpf_cnpj', 'cnpj_cpf', 'cliente_documento'):
                value = re.sub(r'[.\-/\s]', '', value)
                if not value.isdigit() or len(value) not in (11, 14):
                    raise ValueError('Informe 11 dígitos para CPF ou 14 para CNPJ.')
            if field == 'placa':
                value = value.upper().replace('-', '').replace(' ', '')
                if not re.fullmatch(r'[A-Z]{3}\d[A-Z0-9]\d{2}', value):
                    raise ValueError('Informe uma placa brasileira válida.')
            if field == 'email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
                raise ValueError('E-mail inválido.')
        except ValueError as exc:
            raise ValueError(f'{fields[field]}: {exc}') from exc
        data[field] = value
    if migration.entity in ('pagar', 'receber'):
        data['origem_id'] = data.get('origem_id') or hashlib.sha256(json.dumps(
            values, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        counterpart = data.pop('contraparte', '')
        if not data.get('descricao'):
            data['descricao'] = counterpart or data.get('categoria') or (
                'Conta a pagar importada' if migration.entity == 'pagar' else 'Conta a receber importada')
        if data['valor'] <= 0:
            raise ValueError('Valor: deve ser maior que zero.')
        data['entry_type'] = migration.entity.upper()
        data['status'] = 'PENDENTE'
        data['issued_on'] = data.get('issued_on', data['vencimento'])
        data['competence_on'] = data.get('competence_on', data['issued_on'])
        data['reference_type'] = 'MIGRACAO'
        data['reference_id'] = migration.id
    if migration.entity == 'produtos':
        data['codigo'] = data['codigo'].upper()
    if migration.entity == 'ordens_servico':
        combined = data.get('cliente_veiculo', '') or data.get('cliente_nome', '')
        plates = {normalize_plate(match.group()) for match in PLATE_PATTERN.finditer(combined)}
        if len(plates) > 1:
            raise ValueError('Há mais de uma placa no texto do cliente. Separe as colunas antes de importar.')
        if plates:
            extracted = next(iter(plates))
            if data.get('placa') and data['placa'] != extracted:
                raise ValueError('A placa informada diverge da placa no texto do cliente.')
            data['placa'] = extracted
            if not data.get('cliente_veiculo'):
                data['cliente_veiculo'] = combined
        if not data.get('forma_pagamento'):
            payment = re.search(r'(?:forma\s+de\s+pagamento|pagamento)\s*[:=]\s*([^;\n]+)', data.get('observacoes', ''), re.IGNORECASE)
            if payment:
                data['forma_pagamento'] = payment.group(1).strip()
        if not any(data.get(field) for field in ('cliente_documento', 'cliente_nome', 'cliente_veiculo')):
            raise ValueError('Associe CPF/CNPJ, nome do cliente ou a coluna combinada de cliente e veículo.')
        data['numero'] = data['numero'].strip()
        data['status'] = work_order_status(data.pop('status_origem', ''))
        data['current_stage'] = 'PRONTO' if data['status'] in ('FINALIZADA', 'ENTREGUE') else 'RECEPCAO'
        data['installment_count'] = data.get('installment_count', 1)
        data['total_servicos'] = data.get('total_servicos', Decimal('0'))
        data['total_pecas'] = data.get('total_pecas', Decimal('0'))
        computed = data['total_servicos'] + data['total_pecas']
        data['total_geral'] = data.get('total_geral', computed)
        if data['total_geral'] > computed and computed:
            raise ValueError('Valor total: não pode superar serviços + produtos.')
        if data.get('placa'):
            data['placa'] = normalize_plate(data['placa'])
    return data


PLATE_PATTERN = re.compile(r'\b[A-Z]{3}[- ]?\d[A-Z0-9]\d{2}\b', re.IGNORECASE)


def normalize_plate(value):
    value = value.upper().replace('-', '').replace(' ', '')
    if not re.fullmatch(r'[A-Z]{3}\d[A-Z0-9]\d{2}', value):
        raise ValueError('Informe uma placa brasileira válida.')
    return value


def work_order_status(value):
    value = normalize(value)
    if any(word in value for word in ('cancel', 'excluid')):
        return 'CANCELADA'
    if any(word in value for word in ('atendido', 'finaliz', 'faturad', 'concluid')):
        return 'FINALIZADA'
    if any(word in value for word in ('andamento', 'execucao', 'iniciado')):
        return 'EM_ANDAMENTO'
    if 'aguardandopeca' in value:
        return 'AGUARDANDO_PECA'
    return 'ABERTA'


def natural_key(entity, data):
    if entity == 'clientes':
        return ('cpf_cnpj', data['cpf_cnpj']) if data.get('cpf_cnpj') else ('nome', data['nome'].casefold())
    if entity == 'fornecedores':
        return ('cnpj_cpf', data['cnpj_cpf']) if data.get('cnpj_cpf') else ('nome', data['nome'].casefold())
    if entity == 'produtos':
        return 'codigo', data['codigo'].casefold()
    if entity == 'veiculos':
        return 'placa', data['placa']
    if entity == 'servicos':
        return 'nome', data['nome'].casefold()
    if entity == 'ordens_servico':
        return 'numero', data['numero'].casefold()
    return 'origem_id', data['origem_id']


def digest_for(migration, data):
    field, key = natural_key(migration.entity, data)
    namespace = migration.source.casefold().strip() if field == 'origem_id' else ''
    return hashlib.sha256(json.dumps([migration.entity, namespace, field, key], ensure_ascii=False).encode()).hexdigest()


def normalized_document(column):
    for char in ('.', '-', '/', ' '):
        column = func.replace(column, char, '')
    return column


def candidate_client_names(data):
    names = set()
    if data.get('cliente_nome'):
        names.add(data['cliente_nome'].strip().casefold())
    combined = data.get('cliente_veiculo', '').strip()
    if combined:
        plate = PLATE_PATTERN.search(combined)
        without_plate = (combined[:plate.start()] + combined[plate.end():]).strip() if plate else combined
        words = without_plate.split()
        names.update(' '.join(words[:end]).casefold() for end in range(1, len(words) + 1))
    return names


def legacy_work_order_parts(combined):
    plate = PLATE_PATTERN.search(combined or '')
    text = PLATE_PATTERN.sub('', combined or '').strip()
    parts = text.split(None, 1)
    return (parts[0] if parts else 'CLIENTE NÃO INFORMADO',
            parts[1].strip() if len(parts) > 1 else None,
            normalize_plate(plate.group()) if plate else None)


def resolve_work_orders(candidates, results, fallback_client=None):
    documents = {data['cliente_documento'] for _, data, _ in candidates if data.get('cliente_documento')}
    names = set().union(*(candidate_client_names(data) for _, data, _ in candidates))
    clients_by_document = defaultdict(list)
    if documents:
        expr = normalized_document(Client.cpf_cnpj)
        for client_id, document, name in db.session.execute(select(Client.id, expr, Client.nome).where(expr.in_(documents))):
            clients_by_document[document].append((client_id, name))
    clients_by_name = defaultdict(list)
    if names:
        expr = func.lower(func.trim(Client.nome))
        for client_id, name, normalized_name in db.session.execute(select(Client.id, Client.nome, expr).where(expr.in_(names))):
            clients_by_name[normalized_name].append((client_id, name))
    employee_names = {data['vendedor'].strip().casefold() for _, data, _ in candidates if data.get('vendedor')}
    employees = {}
    if employee_names:
        expr = func.lower(func.trim(Employee.nome))
        employees = {name: employee_id for employee_id, name in db.session.execute(
            select(Employee.id, expr).where(expr.in_(employee_names)))}
    valid = []
    vehicles_by_owner_plate = defaultdict(list)
    plates = {data['placa'] for _, data, _ in candidates if data.get('placa')}
    if plates:
        plate_expr = func.upper(func.replace(func.replace(Vehicle.placa, '-', ''), ' ', ''))
        for vehicle_id, client_id, description, plate in db.session.execute(
                select(Vehicle.id, Vehicle.client_id, Vehicle.descricao, plate_expr).where(plate_expr.in_(plates))):
            vehicles_by_owner_plate[(client_id, plate)].append((vehicle_id, description))
    for number, data, digest in candidates:
        matches = clients_by_document.get(data.get('cliente_documento'), [])
        if not matches and not data.get('cliente_documento'):
            matching_names = [(name, rows) for name, rows in clients_by_name.items() if name in candidate_client_names(data)]
            if matching_names:
                matches = max(matching_names, key=lambda item: len(item[0]))[1]
        fallback = len(matches) != 1 and fallback_client is not None
        if len(matches) != 1 and not fallback:
            results.append((number, 'ERRO', 'Cliente não encontrado ou ambíguo. Importe/corrija o cliente primeiro e confira o nome ou CPF/CNPJ.'))
            continue
        combined = data.pop('cliente_veiculo', '') or data.get('cliente_nome', '')
        if fallback:
            client_id, _placeholder_name = fallback_client
            client_name, fallback_vehicle, fallback_plate = legacy_work_order_parts(combined)
            data['veiculo_descricao'] = data.get('veiculo_descricao') or fallback_vehicle
            data['placa'] = data.get('placa') or fallback_plate
        else:
            client_id, client_name = matches[0]
        data['client_id'] = client_id
        data['client_nome'] = client_name
        data.pop('cliente_documento', None)
        data.pop('cliente_nome', None)
        plate_match = PLATE_PATTERN.search(combined)
        if not data.get('placa') and plate_match:
            data['placa'] = normalize_plate(plate_match.group())
        if not data.get('veiculo_descricao') and combined:
            remainder = combined
            if remainder.casefold().startswith(client_name.casefold()):
                remainder = remainder[len(client_name):]
            if plate_match:
                remainder = re.sub(re.escape(plate_match.group()), '', remainder, flags=re.IGNORECASE)
            data['veiculo_descricao'] = remainder.strip()[:160] or None
        if data.get('placa'):
            vehicles = vehicles_by_owner_plate[(client_id, data['placa'])]
            if len(vehicles) == 1:
                data['vehicle_id'] = vehicles[0][0]
                data['veiculo_descricao'] = data.get('veiculo_descricao') or vehicles[0][1]
        seller = data.pop('vendedor', '').strip()
        if seller:
            data['employee_id'] = employees.get(seller.casefold())
            note = f'Responsável na origem: {seller}'
            data['observacoes'] = f"{data.get('observacoes', '').strip()}\n{note}".strip()
        valid.append((number, data, digest))
    return valid


def migration_fallback_client():
    name = 'Cliente VHSys (Importado)'
    client = db.session.scalar(select(Client).where(func.lower(Client.nome) == name.casefold()).limit(1))
    if not client:
        client = Client(nome=name, observacoes='Cliente auxiliar criado para ordens migradas sem vínculo único no cadastro.')
        db.session.add(client)
        db.session.flush()
    return client.id, client.nome


def resolve_payments(candidates, results):
    if not any(data.get('forma_pagamento') for _, data, _ in candidates):
        return candidates
    methods = defaultdict(list)
    for method in db.session.scalars(select(PaymentMethod).where(PaymentMethod.ativo.is_(True))):
        methods[normalize(method.nome)].append(method.id)
    valid = []
    for number, data, digest in candidates:
        name = data.pop('forma_pagamento', '')
        if name:
            matches = methods.get(normalize(name), [])
            if len(matches) != 1:
                results.append((number, 'ERRO', 'Forma de pagamento não encontrada ou ambígua: ' + name[:120] + '. Cadastre/corrija a forma de pagamento antes de importar.'))
                continue
            data['payment_method_id'] = matches[0]
        valid.append((number, data, digest))
    return valid


def existing_keys(entity, data_rows):
    model = SCHEMAS[entity][0]
    groups = defaultdict(set)
    for data in data_rows:
        field, key = natural_key(entity, data)
        if field != 'origem_id':
            groups[field].add(key)
    found = set()
    for field, keys in groups.items():
        column = getattr(model, field)
        expr = normalized_document(column) if field in ('cpf_cnpj', 'cnpj_cpf') else func.lower(func.trim(column))
        if field == 'placa':
            expr = func.upper(func.replace(column, '-', ''))
        for value in db.session.scalars(select(expr).where(expr.in_(keys))):
            found.add((field, value))
    return found


def write_group(migration, candidates):
    """Bulk insert by field set. Savepoint fallback isolates exceptional DB conflicts."""
    if not candidates:
        return
    model = SCHEMAS[migration.entity][0]
    with db.session.begin_nested():
        db.session.execute(insert(MigrationKey), [{'digest': digest, 'migration_id': migration.id}
                                                 for _, _, digest in candidates])
        groups = defaultdict(list)
        for _, data, _ in candidates:
            payload = {key: value for key, value in data.items() if key not in ('origem_id', 'cliente_documento')}
            groups[tuple(sorted(payload))].append(payload)
        for group in groups.values():
            db.session.execute(insert(model.__table__), group)
        if migration.entity == 'ordens_servico':
            numbers = [data['numero'] for _, data, _ in candidates]
            records = db.session.execute(select(WorkOrder.id, WorkOrder.numero, WorkOrder.status).where(
                WorkOrder.numero.in_(numbers))).all()
            db.session.execute(insert(WorkOrderStatusHistory.__table__), [dict(work_order_id=order_id,
                user_id=migration.user_id, status=status, observation=f'Importada na migração #{migration.id}')
                for order_id, _number, status in records])
        if migration.entity == 'produtos':
            balances = {data['codigo']: data for _, data, _ in candidates if data.get('estoque_atual', 0)}
            if balances:
                records = db.session.execute(select(Product.id, Product.codigo).where(Product.codigo.in_(balances))).all()
                db.session.execute(insert(InventoryMovement.__table__), [dict(product_id=pk, movement_type='SALDO_INICIAL',
                    quantity=balances[code]['estoque_atual'], balance_after=balances[code]['estoque_atual'],
                    unit_cost=balances[code].get('custo', 0), user_id=migration.user_id,
                    reference=f'Migração #{migration.id}') for pk, code in records])


def import_batch(migration_id):
    # Serialize a run, including duplicate queued deliveries, until the checkpoint commits.
    migration = db.session.scalar(select(DataMigration).where(DataMigration.id == migration_id).with_for_update())
    if not migration or migration.status != 'IMPORTANDO':
        return
    rows = db.session.execute(select(MigrationRow.__table__).where(MigrationRow.migration_id == migration.id,
        MigrationRow.result == 'PENDENTE').order_by(MigrationRow.number).limit(BATCH_SIZE)).mappings().all()
    mapping = json.loads(migration.mapping_json)
    candidates, results = [], []
    for row in rows:
        try:
            data = convert(migration, json.loads(row['payload']), mapping)
            candidates.append((row['number'], data, digest_for(migration, data)))
        except ValueError as exc:
            results.append((row['number'], 'ERRO', str(exc)))
    if migration.entity == 'veiculos' and candidates:
        documents = {data['cliente_documento'] for _, data, _ in candidates}
        clients = defaultdict(list)
        expr = normalized_document(Client.cpf_cnpj)
        for client_id, document in db.session.execute(select(Client.id, expr).where(expr.in_(documents))):
            clients[document].append(client_id)
        valid = []
        for number, data, digest in candidates:
            matches = clients[data['cliente_documento']]
            if len(matches) != 1:
                results.append((number, 'ERRO', 'Cliente não encontrado ou documento duplicado. Importe/corrija o cliente primeiro.'))
            else:
                data['client_id'] = matches[0]
                valid.append((number, data, digest))
        candidates = valid
    seen = set(db.session.scalars(select(MigrationKey.digest).where(MigrationKey.digest.in_([x[2] for x in candidates])))) if candidates else set()
    existing = existing_keys(migration.entity, [data for _, data, _ in candidates])
    valid = []
    for number, data, digest in candidates:
        if digest in seen or natural_key(migration.entity, data) in existing:
            results.append((number, 'IGNORADO', 'Registro já existente ou repetido no arquivo.'))
        else:
            valid.append((number, data, digest))
            seen.add(digest)
    if migration.entity == 'ordens_servico':
        valid = resolve_work_orders(valid, results, migration_fallback_client())
    valid = resolve_payments(valid, results)
    try:
        write_group(migration, valid)
        results.extend((number, 'IMPORTADO', '') for number, _, _ in valid)
    except (IntegrityError, DataError):
        for candidate in valid:
            try:
                write_group(migration, [candidate])
                results.append((candidate[0], 'IMPORTADO', ''))
            except (IntegrityError, DataError):
                results.append((candidate[0], 'ERRO', 'Conflito de cadastro ou valor incompatível com o banco. Revise a linha.'))
    if results:
        table = MigrationRow.__table__
        statement = update(table).where(table.c.migration_id == migration.id, table.c.number == bindparam('_number')).values(
            result=bindparam('_result'), message=bindparam('_message'))
        db.session.execute(statement, [{'_number': number, '_result': result, '_message': message[:500]}
                                      for number, result, message in results])
        migration.processed = rows[-1]['number']
        migration.imported += sum(result == 'IMPORTADO' for _, result, _ in results)
        migration.skipped += sum(result == 'IGNORADO' for _, result, _ in results)
        migration.errors += sum(result == 'ERRO' for _, result, _ in results)
        db.session.add(AuditEvent(user_id=migration.user_id, action='MIGRACAO_LOTE', entity_type='DataMigration',
            entity_id=migration.id, details=json.dumps({'registros': len(rows), 'ate': migration.processed})))
    if migration.imported + migration.skipped + migration.errors >= migration.total:
        migration.status = 'CONCLUIDA'
    else:
        enqueue('MIGRATION_IMPORT', {'migration_id': migration.id})
