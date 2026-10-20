"""Wipe operational data and reload everything from vhsys HTML exports; default is a read-only preview.

Usage: python scripts/reload_vhsys.py <pasta-com-os-html> [--apply]
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
import gzip
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import delete, insert, select
from app import create_app
from app.models import db
from app.operations.models import AuditEvent
from app.data_migration.finance_replace import money, parse_finance_export, source_date
from app.data_migration.service import PLATE_PATTERN, normalize, work_order_status
from app.services import work_order_receivable_description

KEEP = {'users', 'system_admins', 'system_settings', 'company_partners', 'fiscal_api_configs', 'managed_companies',
        'workshop_resources', 'chart_of_accounts', 'cost_centers', 'commission_rules', 'stock_locations',
        'audit_events', 'alembic_version'}
# Saldos informados pelo usuário em 20/10/2026; demais contas do vhsys são ignoradas.
ACCOUNTS = {'juridica': ('JURIDICA', 'Itau', '6393', '202272', Decimal('12679.76')),
            'dinheiro': ('Dinheiro', None, None, None, Decimal('16213.92'))}
METHOD_TYPES = {'dinheiro': ('DINHEIRO', False), 'pix': ('PIX', False), 'cartaodedebito': ('DEBITO', False),
                'cartaodecredito': ('CREDITO', True), 'boleto': ('BOLETO', True)}
OS_REF = re.compile(r'(?:ordemdeservico|os)(\d+)')


def clean(value):
    return re.sub(r'\s+', ' ', value).strip()


def grid(path):
    """Rows of a vhsys report grid; item subtables go to row['_sub']."""
    # Streamed: loading the 27 MB OS export whole needs ~560 MB, over the hosting memory limit.
    fields, rows = None, []
    for _, tr in etree.iterparse(str(path), events=('end',), tag='tr', html=True, encoding='utf-8', recover=True):
        section = tr.getparent()
        if section is None or section.getparent() is None or section.getparent().get('id') != 'tblGrid':
            continue
        cls = tr.get('class') or ''
        if section.tag == 'thead':
            fields = [h.get('data-field') for h in tr.xpath('./th')]
            continue
        if 'table-row-body' in cls:
            rows.append({**{f: clean(''.join(td.itertext())) for f, td in zip(fields, tr.xpath('./td'))},
                         '_id': tr.get('data-id'), '_sub': []})
        elif 'Table_L1' in cls and rows and tr.get('data-id') == rows[-1]['_id']:
            sub = tr.xpath('.//table[@data-subtable="true"]')
            if sub:
                sf = [h.get('data-field') for h in sub[0].xpath('./thead/tr/th')]
                for item in sub[0].xpath('./tbody/tr'):
                    cells = [clean(''.join(td.itertext())) for td in item.xpath('./td')]
                    if len(cells) == len(sf):
                        rows[-1]['_sub'].append(dict(zip(sf, cells)))
        tr.clear()
        while tr.getprevious() is not None:
            del section[0]
    return rows


def qty(value):
    value = (value or '0').replace('.', '').replace(',', '.') if ',' in (value or '') else (value or '0')
    return Decimal(value).quantize(Decimal('0.01'))


def cut(value, size):
    value = (value or '').strip()
    return value[:size] or None


def address(r):
    city = ' / '.join(x for x in (r.get('Cidade'), r.get('Estado')) if x)
    parts = [', '.join(x for x in (r.get('Endereco'), r.get('Numero')) if x), r.get('Complemento'), r.get('Bairro'),
             city, ('CEP ' + r['CEP']) if r.get('CEP') else '']
    return cut(' - '.join(p for p in parts if p), 255)


def plate_of(name):
    match = PLATE_PATTERN.search(name or '')
    if not match:
        return None, name
    plate = re.sub(r'[\s-]', '', match.group(0)).upper()
    rest = clean((name[:match.start()] + ' ' + name[match.end():]).strip(' -'))
    return plate, rest


def build(base):
    now = datetime.now()
    stamp = lambda value: source_date(value, timestamp=True) or now
    rows = {}
    ids = Counter()

    def add(table, **values):
        ids[table] += 1
        values['id'] = ids[table]
        rows.setdefault(table, []).append(values)
        return values['id']

    for key, (nome, banco, agencia, conta, saldo) in ACCOUNTS.items():
        add('bank_accounts', nome=nome, banco=banco, agencia=agencia, conta=conta, saldo_inicial=saldo,
            saldo_atual=saldo, ativo=True)
    account_ids = {key: i + 1 for i, key in enumerate(ACCOUNTS)}

    orders = grid(base / 'OrdemServico.html')
    receber = parse_finance_export(base / 'ContasReceber.html', 'RECEBER')
    pagar = parse_finance_export(base / 'ContasPagar.html', 'PAGAR')
    extrato = grid(base / 'Extrato24-25.html') + grid(base / 'Extrato25-26.html')

    # Formas de pagamento: tudo o que aparece nos títulos e no extrato ("PIX" e "Pix" são a mesma).
    method_names = {}
    for name in [r['method'] for r in receber + pagar] + [r['FormaPag'] for r in extrato]:
        if name and normalize(name) not in method_names:
            method_names[normalize(name)] = 'Pix' if normalize(name) == 'pix' else name
    method_ids = {}
    for key, name in method_names.items():
        tipo, parcela = METHOD_TYPES.get(key, ('OUTRO', False))
        method_ids[key] = add('payment_methods', nome=name, tipo=tipo, permite_parcelamento=parcela,
                              parcelas_maximas=12 if parcela else 1, ativo=True)

    employee_ids = {}
    for field, role in (('Profissional', 'Mecânico'), ('Vendedor', 'Vendedor')):
        for r in orders:
            if r[field] and normalize(r[field]) not in employee_ids:
                employee_ids[normalize(r[field])] = add('employees', nome=cut(r[field], 120), funcao=role, ativo=True)

    supplier_ids, supplier_docs = {}, {}
    for r in grid(base / 'Clientes.html'):
        sid = add('suppliers', nome=cut(r['Fantasia'] or r['Nome'], 160), razao_social=cut(r['Nome'], 160),
                  cnpj_cpf=cut(r['CNPJCPF'], 20), inscricao_estadual=cut(r['IE'], 40),
                  telefone=cut(r['Celular'] or r['Telefone'], 30), email=cut(r['Email'], 120), endereco=address(r),
                  observacoes=r['Observacao'] or None, ativo=True, created_at=stamp(r['DataCad']))
        supplier_ids[normalize(r['Nome'])] = sid
        if r['CNPJCPF']:
            supplier_docs[re.sub(r'\D', '', r['CNPJCPF'])] = sid

    client_ids = {}
    for r in grid(base / 'ClientesApenas.html'):
        notes = [r['Observacao']] + [f'{label}: {r[f]}' for f, label in (('Fantasia', 'Fantasia'), ('Contato', 'Contato'),
                 ('RG', 'RG'), ('DataNascimento', 'Nascimento'), ('Telefone', 'Telefone fixo')) if r[f]]
        client_ids[normalize(r['Nome'])] = add(
            'clients', nome=cut(r['Nome'], 160), cpf_cnpj=cut(r['CNPJCPF'], 20), inscricao_estadual=cut(r['IE'], 40),
            telefone=cut(r['Celular'] or r['Telefone'], 30), email=cut(r['Email'], 120), endereco=address(r),
            observacoes='\n'.join(n for n in notes if n) or None, created_at=stamp(r['DataCad']))
    registered = len(client_ids)

    service_ids = {}
    for r in grid(base / 'ServicosMaisVendidos.html'):
        service_ids.setdefault(normalize(r['Servico']), add('services', nome=cut(r['Servico'], 120),
                                                            preco_base=money(r['ValorServ']), ativo=True))

    # Produtos vêm das entradas; o "Estoque Atual" da entrada mais recente vale como saldo atual.
    entries = sorted(grid(base / 'EntradasMercadoria.html'), key=lambda r: (source_date(r['DataPedido']), int(r['Entrada'])))
    sale_price = {}
    for r in orders:
        for item in r['_sub']:
            if normalize(item['Tipo']) == 'produto':
                sale_price[normalize(item['Produto'])] = money(item['ValorUnit'])
    products, codes = {}, set()
    for r in entries:
        for item in r['_sub']:
            key = normalize(item['Produto'])
            product = products.get(key)
            if not product:
                code = cut(item['Codigo'], 36) or 'VH'
                base_code, n = code, 1
                while code in codes:
                    n += 1
                    code = f'{base_code}-{n}'
                codes.add(code)
                ids['products'] += 1
                product = products[key] = dict(id=ids['products'], codigo=code, nome=cut(item['Produto'], 120),
                                               unidade=cut(item['Unidade'], 20) or 'UN', ativo=True, estoque_minimo=0)
            product.update(ncm=cut(item['NCM'], 20), cfop=cut(item['CFOP'], 10), custo=money(item['ValorUnit']),
                           estoque_atual=qty(item['EstoqueAtual']))
    for key, product in products.items():
        product['preco_venda'] = sale_price.get(key, product['custo'])
    rows['products'] = list(products.values())

    for r in entries:
        doc = re.sub(r'\D', '', r['CNPJ'])
        sid = supplier_docs.get(doc) if doc else None
        sid = sid or supplier_ids.get(normalize(r['Fornecedor']))
        if not sid:
            sid = add('suppliers', nome=cut(r['Fornecedor'], 160) or 'Fornecedor sem nome', razao_social=cut(r['Fornecedor'], 160),
                      cnpj_cpf=cut(r['CNPJ'], 20), telefone=cut(r['Telefone'], 30), email=cut(r['Email'], 120),
                      endereco=address(r), ativo=True)
            supplier_ids[normalize(r['Fornecedor'])] = sid
            if doc:
                supplier_docs[doc] = sid
        notes = [r['Obs']] + [f'{label}: {r[f]}' for f, label in (('Entrada', 'Entrada vhsys'), ('Chave', 'Chave NF-e'),
                 ('ValorDesconto', 'Desconto')) if r[f] and r[f] != 'R$ 0,00']
        eid = add('stock_entries', supplier_id=sid, numero_nota=cut(r['NFCompra'], 50),
                  data_emissao=source_date(r['DataEmissao']) or source_date(r['DataPedido']),
                  data_entrada=source_date(r['DataPedido']), transportadora=cut(r['Transportadora'], 120),
                  valor_frete=money(r['ValorFrete']), valor_total=money(r['ValorTotal']), status='CONCLUIDA',
                  observacoes='\n'.join(n for n in notes if n) or None, created_at=stamp(r['DataCad']))
        for item in r['_sub']:
            add('stock_entry_items', stock_entry_id=eid, product_id=products[normalize(item['Produto'])]['id'],
                quantidade=qty(item['Qtde']), custo_unitario=money(item['ValorUnit']), total_item=money(item['ValorTotal']))

    # Forma de pagamento da OS: contas a receber; quando vazia, o lançamento do extrato da mesma OS.
    by_order = defaultdict(list)
    for record in receber:
        match = OS_REF.fullmatch(normalize(record['payload']['descricao']))
        if match:
            by_order[match.group(1)].append(record)
    extrato_method = {}
    for r in extrato:
        match = OS_REF.fullmatch(normalize(r['Lancamento']))
        if match and r['FormaPag']:
            extrato_method.setdefault(match.group(1), r['FormaPag'])

    vehicles, order_ids, no_payment, payment_source = {}, {}, [], Counter()
    for r in orders:
        number = r['Ordem']
        if number in order_ids:
            raise ValueError('OS repetida: ' + number)
        name = r['Cliente'] or 'Cliente VHSys (Importado)'
        client_id = client_ids.get(normalize(name))
        if not client_id:
            client_id = client_ids[normalize(name)] = add('clients', nome=cut(name, 160), created_at=stamp(r['DataCad']),
                                                          observacoes='Cadastro criado a partir da OS do vhsys.')
        plate, description = plate_of(name)
        vehicle_id = None
        if plate:
            vehicle_id = vehicles.get((client_id, plate))
            if not vehicle_id:
                vehicle_id = vehicles[(client_id, plate)] = add('vehicles', client_id=client_id, placa=plate,
                                                                descricao=cut(description, 160) or plate, ativo=True)
        status = work_order_status(r['Situacao'])
        closed = status in ('FINALIZADA', 'ENTREGUE', 'CANCELADA')
        totals = defaultdict(Decimal)
        counts = Counter()
        for record in by_order.get(number, []):
            method = normalize(record['method']) or normalize(extrato_method.get(number, ''))
            if method:
                totals[method] += record['payload']['valor']
                counts[method] += 1
        if not totals and normalize(extrato_method.get(number, '')):
            totals[normalize(extrato_method[number])] = money(r['ValorTotal'])
            counts[normalize(extrato_method[number])] = 1
        main_method = max(totals, key=totals.get) if totals else None
        payment_source['receber' if by_order.get(number) and totals else 'extrato' if totals else 'sem'] += 1
        if not main_method and money(r['ValorTotal']) and status != 'CANCELADA':
            no_payment.append(number)
        employee = normalize(r['Profissional']) or normalize(r['Vendedor'])
        notes = [r['Observacoes']] + [f'Vendedor: {r["Vendedor"]}' for _ in [0] if r['Vendedor'] and r['Profissional']
                                      and normalize(r['Vendedor']) != normalize(r['Profissional'])]
        oid = order_ids[number] = add(
            'work_orders', numero=number, client_id=client_id, vehicle_id=vehicle_id, employee_id=employee_ids.get(employee),
            payment_method_id=method_ids.get(main_method), status=status,
            data_entrada=source_date(r['DataPedido']),
            data_saida=(source_date(r['DataRealizacao']) or source_date(r['DataEntrega'])) if closed else None,
            current_stage='ENTREGUE' if closed else 'RECEPCAO', placa=plate, veiculo_descricao=cut(description, 160) if plate else None,
            observacoes='\n'.join(n for n in notes if n) or None, installment_count=max(1, int(r['TotalParcelas'] or 1)),
            client_nome=cut(name, 160), emitir_nota=normalize(r['NFSeEmitida']) == 'sim',
            estoque_baixado=closed or normalize(r['Estoque']) == 'sim', total_pecas=money(r['ValorProdutos']),
            total_servicos=money(r['ValorServicos']), total_geral=money(r['ValorTotal']), version=0,
            created_at=stamp(r['DataCad']), updated_at=stamp(r['DataMod'] or r['DataCad']))
        add('work_order_status_history', work_order_id=oid, status=status, observation='Importada do vhsys.',
            changed_at=stamp(r['DataMod'] or r['DataCad']))
        for method, value in totals.items():
            add('work_order_payments', work_order_id=oid, payment_method_id=method_ids[method], valor=value,
                installment_count=counts[method])
        for item in r['_sub']:
            if normalize(item['ItemRejeitado']) in ('sim', 's', '1'):
                continue
            kind = 'PECA' if normalize(item['Tipo']) == 'produto' else 'SERVICO'
            q, unit, total = qty(item['Qtde']), money(item['ValorUnit']), money(item['ValorTotal'])
            ref = (products.get(normalize(item['Produto'])) or {}).get('id') if kind == 'PECA' else service_ids.get(normalize(item['Produto']))
            add('work_order_items', work_order_id=oid, item_type=kind, reference_id=ref, descricao=cut(item['Produto'], 255) or '-',
                quantidade=q, valor_unitario=unit, desconto=max(Decimal('0'), q * unit - total), total=total)

    orphan = 0
    for record in receber + pagar:
        data = record['payload']
        data['payment_method_id'] = method_ids.get(normalize(record['method']))
        data['bank_account_id'] = account_ids.get(normalize(record['account']))
        match = OS_REF.fullmatch(normalize(data['descricao'])) if data['entry_type'] == 'RECEBER' else None
        if match and match.group(1) in order_ids:
            oid = order_ids[match.group(1)]
            order = rows['work_orders'][oid - 1]
            data.update(reference_type='OS', reference_id=oid, descricao=work_order_receivable_description(
                SimpleNamespace(client_nome=order['client_nome'], client=None, numero=order['numero'])))
        elif match:
            orphan += 1
        data.setdefault('created_at', now)
        data.setdefault('updated_at', data['created_at'])
        data['version'] = 0
        add('financial_entries', **data)

    for r in grid(base / 'NotasFiscaisServico.html'):
        add('fiscal_documents', provider_name='VHSYS', document_type='NFSE', environment='PRODUCAO',
            status='CANCELADO' if 'cancel' in normalize(r['Situacao']) else 'AUTORIZADO', numero=cut(r['Nota'], 30),
            serie=None, external_id=cut(r['RPS'], 80), access_key=cut(r['Chave'], 80),
            response_payload=json.dumps({k: v for k, v in r.items() if not k.startswith('_')}, ensure_ascii=False),
            created_at=stamp(r['DataEmissao'] or r['DataPedido']), updated_at=stamp(r['DataMod'] or r['DataPedido']))

    report = dict(counts={t: len(v) for t, v in rows.items()}, registered_clients=registered,
                  payment_source=dict(payment_source), orders_without_payment=no_payment,
                  receivables_of_missing_orders=orphan,
                  receber=str(sum(r['payload']['valor'] for r in receber)), pagar=str(sum(r['payload']['valor'] for r in pagar)),
                  os_total=str(sum(money(r['ValorTotal']) for r in orders)))
    return rows, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    rows, report = build(args.folder)
    print(json.dumps({**report, 'orders_without_payment': len(report['orders_without_payment'])}, indent=1), flush=True)
    app = create_app({'AUTO_CREATE_SCHEMA': False})
    with app.app_context():
        tables = [t for t in reversed(db.metadata.sorted_tables) if t.name not in KEEP]
        unknown = set(rows) - {t.name for t in tables}
        if unknown:
            raise ValueError('Tabelas fora da limpeza: ' + repr(unknown))
        current = {t.name: db.session.scalar(select(db.func.count()).select_from(t)) for t in tables}
        print('Atual (será apagado):', {k: v for k, v in current.items() if v}, flush=True)
        if not args.apply:
            return
        try:
            root = Path(app.instance_path) / 'backups'
            root.mkdir(parents=True, exist_ok=True)
            backup = root / ('before-vhsys-reload-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.jsonl.gz')
            with gzip.open(backup, 'xt', encoding='utf-8') as stream:  # one {"table", "row"} per line, streamed
                for table in tables:
                    for row in db.session.execute(select(table).execution_options(yield_per=1000)).mappings():
                        stream.write(json.dumps({'table': table.name, 'row': dict(row)}, ensure_ascii=False, default=str) + '\n')
            with gzip.open(backup, 'rt', encoding='utf-8') as stream:
                saved = Counter(json.loads(line)['table'] for line in stream)
            if any(saved[name] != count for name, count in current.items()):
                raise ValueError('Falha na verificação do backup.')
            print('Backup verificado:', backup, flush=True)
            for table in tables:
                db.session.execute(delete(table))
            for table in reversed(tables):
                groups = {}  # executemany needs one key set per batch; absent keys keep column defaults
                for row in rows.get(table.name, []):
                    groups.setdefault(tuple(sorted(row)), []).append(row)
                for group in groups.values():
                    for start in range(0, len(group), 500):
                        db.session.execute(insert(table), group[start:start + 500])
            db.session.add(AuditEvent(action='RECARGA_VHSYS', entity_type='Sistema', details=json.dumps(
                {'backup': str(backup), 'removed': current, 'inserted': report['counts']}, default=str)))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        print('COMMITTED', report['counts'], flush=True)
        print('OS sem forma de pagamento:', ' '.join(report['orders_without_payment']), flush=True)


if __name__ == '__main__':
    main()
