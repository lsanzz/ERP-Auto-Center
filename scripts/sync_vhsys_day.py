"""Atualiza O.S. e contas a receber a partir de exportações parciais do vhsys (ex.: o dia de ontem e hoje).

Uso:
  python scripts/sync_vhsys_day.py extract <pasta> <saida.json>   # local: lê OrdensHoje/ContasReceberHoje/ExtratoHoje.html
  python scripts/sync_vhsys_day.py apply <dados.json> [--apply]   # servidor: prévia por padrão; --apply grava

O vhsys manda: cada O.S. do arquivo substitui cliente, itens, valores e situação da O.S. de mesmo número
(criando-a se não existir). Contas a receber da O.S. são criadas ou baixadas conforme o arquivo; o extrato
só baixa parcelas ainda abertas (ex.: cartão compensado). Lançamentos que não são de O.S. não são tocados.
"""
import argparse
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
import gzip
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

OS_REF = re.compile(r'(?:ordemdeservico|os)(\d+)')


def extract(folder: Path) -> dict:
    from reload_vhsys import grid
    from app.data_migration.service import normalize
    orders = [{k: v for k, v in row.items() if k not in ('_id',)} for row in grid(folder / 'OrdensHoje.html')]
    receber = grid(folder / 'ContasReceberHoje.html')
    extrato = grid(folder / 'ExtratoHoje.html')
    for row in receber + extrato:
        row.pop('_sub', None); row.pop('_id', None)
        match = OS_REF.fullmatch(normalize(row.get('NomeConta') or row.get('Lancamento') or ''))
        row['os'] = match.group(1) if match else None
    return {'orders': orders, 'receber': [r for r in receber if r['os']], 'extrato': [r for r in extrato if r['os']],
            'ignored_receber': [r['NomeConta'] for r in receber if not r['os']],
            'ignored_extrato': [r['Lancamento'] for r in extrato if not r['os']]}


def apply(data: dict, commit: bool):
    from app import create_app
    from app.data_migration.finance_replace import money, source_date
    from app.data_migration.service import normalize, work_order_status
    from app.fleet.models import Vehicle
    from app.models import BankAccount, Client, Employee, FinancialEntry, PaymentMethod, WorkOrder, WorkOrderItem, WorkOrderPayment, db
    from app.operations.models import AuditEvent
    from app.services import create_financial_entries, settle_financial_entry, work_order_receivable_description
    from reload_vhsys import cut, plate_of, qty

    app = create_app({'AUTO_CREATE_SCHEMA': False})
    with app.app_context():
        report = []
        log = lambda *parts: report.append(' '.join(str(p) for p in parts))
        accounts = {normalize(a.nome): a.id for a in BankAccount.query.filter_by(ativo=True)}
        methods = {normalize(m.nome): m.id for m in PaymentMethod.query}
        method_id = lambda name: methods.get('pix' if normalize(name) == 'pix' else normalize(name)) if name else None
        employees = {normalize(e.nome): e for e in Employee.query}
        before = {}

        def employee_for(name):
            key = normalize(name)
            if not key:
                return None
            if key not in employees:
                employees[key] = Employee(nome=cut(name, 120), funcao='Mecânico', ativo=True)
                db.session.add(employees[key]); db.session.flush()
                log('  + funcionário', name)
            return employees[key].id

        def client_for(name):
            name = (name or 'Cliente VHSys (Importado)').strip()
            found = Client.query.filter(db.func.lower(Client.nome) == name.lower()).first()
            if found:
                return found
            client = Client(nome=cut(name, 160), observacoes='Cadastro criado a partir da O.S. do vhsys.')
            db.session.add(client); db.session.flush()
            log('  + cliente', name)
            return client

        receber_by_os, extrato_by_os = defaultdict(list), defaultdict(list)
        for row in data['receber']:
            receber_by_os[row['os']].append(row)
        for row in data['extrato']:
            if money(row['Entrada']) > 0:
                extrato_by_os[row['os']].append(row)

        for row in data['orders']:
            number = row['Ordem']
            order = WorkOrder.query.filter_by(numero=number).first()
            if order:
                before[number] = {c.name: getattr(order, c.name) for c in WorkOrder.__table__.columns}
            created = order is None
            name = row['Cliente'] or 'Cliente VHSys (Importado)'
            client = order.client if order and normalize(order.client_nome or '') == normalize(name) else client_for(name)
            plate, description = plate_of(name)
            vehicle = None
            if plate:
                vehicle = Vehicle.query.filter_by(client_id=client.id, placa=plate).first()
                if not vehicle:
                    vehicle = Vehicle(client_id=client.id, placa=plate, descricao=cut(description, 160) or plate, ativo=True)
                    db.session.add(vehicle); db.session.flush()
            status = work_order_status(row['Situacao'])
            closed = status in ('FINALIZADA', 'ENTREGUE', 'CANCELADA')
            if created:
                order = WorkOrder(numero=number, version=0)
                db.session.add(order)
            order.client_id, order.client_nome, order.vehicle_id = client.id, cut(name, 160), vehicle.id if vehicle else None
            order.placa, order.veiculo_descricao = plate, cut(description, 160) if plate else None
            order.employee_id = employee_for(row['Profissional']) or employee_for(row['Vendedor'])
            order.status, order.current_stage = status, 'ENTREGUE' if closed else (order.current_stage or 'RECEPCAO')
            order.data_entrada = source_date(row['DataPedido'])
            order.data_saida = (source_date(row['DataRealizacao']) or source_date(row['DataEntrega'])) if closed else None
            order.total_servicos, order.total_pecas, order.total_geral = (money(row['ValorServicos']), money(row['ValorProdutos']), money(row['ValorTotal']))
            order.installment_count = max(1, int(row['TotalParcelas'] or 1))
            order.observacoes = row['Observacoes'] or None
            order.estoque_baixado = closed or normalize(row['Estoque']) == 'sim'
            db.session.flush()
            # Itens: a O.S. do vhsys é a referência; troca todos.
            WorkOrderItem.query.filter_by(work_order_id=order.id).delete()
            for item in row['_sub']:
                if normalize(item.get('ItemRejeitado')) in ('sim', 's', '1'):
                    continue
                q, unit, total = qty(item['Qtde']), money(item['ValorUnit']), money(item['ValorTotal'])
                db.session.add(WorkOrderItem(work_order_id=order.id, item_type='PECA' if normalize(item['Tipo']) == 'produto' else 'SERVICO',
                                             descricao=cut(item['Produto'], 255) or '-', quantidade=q, valor_unitario=unit,
                                             desconto=max(Decimal('0'), q * unit - total), total=total))
            # Forma de pagamento: contas a receber do arquivo; senão extrato.
            file_receber = receber_by_os.get(number, [])
            totals = defaultdict(Decimal)
            for rec in file_receber:
                if method_id(rec['FormaPag']):
                    totals[method_id(rec['FormaPag'])] += money(rec['ValorOriginal'])
            if not totals:
                for ext in extrato_by_os.get(number, []):
                    if method_id(ext['FormaPag']):
                        totals[method_id(ext['FormaPag'])] += money(ext['Entrada'])
            # Só troca a forma da O.S. quando o arquivo cobre o total (senão é só uma parcela, ex.: Pix de entrada).
            if totals and (sum(totals.values()) == order.total_geral or not order.payments):
                order.payment_method_id = max(totals, key=totals.get)
                WorkOrderPayment.query.filter_by(work_order_id=order.id).delete()
                for mid, value in totals.items():
                    db.session.add(WorkOrderPayment(work_order_id=order.id, payment_method_id=mid, valor=value, installment_count=1))
            log(('+ criada ' if created else '~ atualizada ') + f'O.S. {number}', name, f'R$ {order.total_geral}', status,
                f'{len(row["_sub"])} itens')

            # Contas a receber da O.S.
            entries = FinancialEntry.query.filter_by(reference_type='OS', reference_id=order.id).order_by(FinancialEntry.id).all()
            used = set()
            for rec in file_receber:
                valor = money(rec['ValorOriginal'])
                paid = normalize(rec['Situacao']).startswith('pago')
                match = next((e for e in entries if e.id not in used and e.valor == valor), None)
                bank = accounts.get(normalize(rec['Banco']))
                kwargs = dict(payment_method_id=method_id(rec['FormaPag']), payment_receipt_at=source_date(rec['DataPago']),
                              bank_account_id=bank, valor_baixa=str(money(rec['ValorBaixado'])), juros=str(money(rec['Juros'])),
                              desconto=str(money(rec['Desconto'])), taxa=str(money(rec['Taxa'])), acrescimo=str(money(rec['Acrescimos'])))
                if match:
                    used.add(match.id)
                    if paid and match.status == 'PENDENTE':
                        settle_financial_entry(match, **kwargs)
                        log(f'  $ baixada R$ {valor} ({rec["FormaPag"]}) recebido R$ {money(rec["ValorPago"])} em {rec["DataPago"]}')
                    else:
                        log(f'  = conta R$ {valor} já {match.status.lower()}')
                    continue
                entry = create_financial_entries('RECEBER', work_order_receivable_description(order), 'Ordens de Serviço', valor,
                                                 source_date(rec['Vencimento']), payment_method_id=method_id(rec['FormaPag']),
                                                 bank_account_id=bank, reference_type='OS', reference_id=order.id)[0]
                used.add(entry.id)
                if paid:
                    settle_financial_entry(entry, **kwargs)
                log(f'  + conta R$ {valor} ({rec["FormaPag"]})', 'recebida' if paid else 'em aberto')
            # Extrato: baixa parcela ainda aberta (ex.: cartão), com a diferença como taxa da operadora.
            entries = FinancialEntry.query.filter_by(reference_type='OS', reference_id=order.id, status='PENDENTE').all()
            for ext in extrato_by_os.get(number, []):
                amount = money(ext['Entrada'])
                if any(normalize(r['Situacao']).startswith('pago') and money(r['ValorPago']) == amount for r in file_receber):
                    continue
                match = next((e for e in entries if e.status == 'PENDENTE' and e.valor >= amount and e.valor - amount <= e.valor * Decimal('0.15')), None)
                if match:
                    settle_financial_entry(match, payment_method_id=method_id(ext['FormaPag']), payment_receipt_at=source_date(ext['Data']),
                                           bank_account_id=accounts.get(normalize(ext['Banco'])), valor_baixa=str(match.valor),
                                           desconto=str(match.valor - amount))
                    log(f'  $ baixada pelo extrato R$ {match.valor} -> R$ {amount} em {ext["Data"]}')

        # O.S. que só aparecem no extrato (recebimentos de O.S. de dias anteriores).
        for number, rows in extrato_by_os.items():
            if any(r['Ordem'] == number for r in data['orders']):
                continue
            order = WorkOrder.query.filter_by(numero=number).first()
            if not order:
                log(f'! extrato cita O.S. {number}, que não existe no sistema'); continue
            for ext in rows:
                amount = money(ext['Entrada'])
                pending = FinancialEntry.query.filter_by(reference_type='OS', reference_id=order.id, status='PENDENTE').all()
                match = next((e for e in pending if e.valor >= amount and e.valor - amount <= e.valor * Decimal('0.15')), None)
                if match:
                    settle_financial_entry(match, payment_method_id=method_id(ext['FormaPag']), payment_receipt_at=source_date(ext['Data']),
                                           bank_account_id=accounts.get(normalize(ext['Banco'])), valor_baixa=str(match.valor),
                                           desconto=str(match.valor - amount))
                    log(f'$ O.S. {number}: baixada pelo extrato R$ {match.valor} -> R$ {amount} em {ext["Data"]}')
                else:
                    log(f'= O.S. {number}: R$ {amount} do extrato já estava recebido')

        log('Ignorados (não são O.S.):', len(data['ignored_receber']), 'contas a receber,', len(data['ignored_extrato']), 'lançamentos do extrato')
        balances = {a.nome: str(a.saldo_atual) for a in BankAccount.query.filter_by(ativo=True)}
        log('Saldos após:', balances)
        print('\n'.join(report), flush=True)
        if not commit:
            db.session.rollback()
            print('PRÉVIA: nada foi gravado. Rode com --apply para gravar.', flush=True)
            return
        root = Path(app.instance_path) / 'backups'
        root.mkdir(parents=True, exist_ok=True)
        backup = root / ('before-vhsys-day-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json.gz')
        with gzip.open(backup, 'wt', encoding='utf-8') as stream:
            json.dump({'orders_before': before}, stream, default=str, ensure_ascii=False)
        db.session.add(AuditEvent(action='SYNC_VHSYS_DIA', entity_type='WorkOrder', details=json.dumps(
            {'orders': [r['Ordem'] for r in data['orders']], 'backup': str(backup)}, ensure_ascii=False)))
        db.session.commit()
        print('COMMITTED · backup', backup, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    ex = sub.add_parser('extract'); ex.add_argument('folder', type=Path); ex.add_argument('out', type=Path)
    ap = sub.add_parser('apply'); ap.add_argument('data', type=Path); ap.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.cmd == 'extract':
        args.out.write_text(json.dumps(extract(args.folder), ensure_ascii=False), encoding='utf-8')
        print('ok', args.out)
    else:
        raw = gzip.decompress(args.data.read_bytes()) if args.data.suffix == '.gz' else args.data.read_bytes()
        apply(json.loads(raw.decode('utf-8')), args.apply)


if __name__ == '__main__':
    main()
