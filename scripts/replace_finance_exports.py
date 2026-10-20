"""Replace all payables/receivables from validated files; default is read-only preview."""
import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select, delete, insert
from app import create_app
from app.models import db, FinancialEntry, BankAccount, BankReconciliation, PaymentMethod, WorkOrder
from app.operations.models import AuditEvent
from app.data_migration.models import DataMigration, MigrationKey
from app.data_migration.finance_replace import parse_finance_export
from app.data_migration.service import normalize
from app.services import work_order_receivable_description


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receber', type=Path)
    parser.add_argument('pagar', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    records = parse_finance_export(args.receber, 'RECEBER') + parse_finance_export(args.pagar, 'PAGAR')
    print('Parsed:', dict(Counter((r['payload']['entry_type'], r['payload']['status']) for r in records)), flush=True)
    app = create_app({'AUTO_CREATE_SCHEMA': False})
    with app.app_context():
        try:
            if db.session.scalar(select(DataMigration.id).where(DataMigration.entity.in_(['pagar','receber']),
                    DataMigration.status == 'IMPORTANDO').limit(1)):
                raise ValueError('Há uma importação financeira em andamento.')
            accounts_list = list(db.session.scalars(select(BankAccount).with_for_update() if args.apply else select(BankAccount)))
            accounts = {normalize(a.nome): a for a in accounts_list}
            if len(accounts) != len(accounts_list):
                raise ValueError('Contas bancárias com nomes ambíguos.')
            for key in ('juridica', 'dinheiro'):
                if key not in accounts:
                    raise ValueError('Conta solicitada não encontrada: ' + key)
            unknown_accounts = {r['account'] for r in records if r['account'] and normalize(r['account']) not in accounts}
            if unknown_accounts:
                raise ValueError('Contas não cadastradas: ' + repr(unknown_accounts))
            methods = {normalize(m.nome): m.id for m in db.session.scalars(select(PaymentMethod))}
            missing_methods = {r['method'] for r in records if r['method'] and normalize(r['method']) not in methods}
            orders = {order.numero: order for order in db.session.scalars(select(WorkOrder)).all()}
            query = select(FinancialEntry.__table__).where(FinancialEntry.entry_type.in_(['PAGAR','RECEBER']))
            old = list(db.session.execute(query.with_for_update() if args.apply else query).mappings())
            reconciliations = list(db.session.execute(select(BankReconciliation.__table__).where(
                BankReconciliation.financial_entry_id.in_([r['id'] for r in old]))).mappings())
            keys_query = select(MigrationKey.__table__).where(MigrationKey.migration_id.in_(select(DataMigration.id).where(
                DataMigration.entity.in_(['pagar','receber']))))
            keys = list(db.session.execute(keys_query).mappings())
            print('Replace:',len(old),'entries; reconciliations:',len(reconciliations),'new methods:',sorted(missing_methods),flush=True)
            if not args.apply:
                db.session.rollback()
                return
            root = Path(app.instance_path) / 'backups'
            root.mkdir(parents=True, exist_ok=True)
            backup = root / ('finance-before-replacement-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json.gz')
            snapshot = dict(financial_entries=[dict(r) for r in old], bank_reconciliations=[dict(r) for r in reconciliations],
                migration_keys=[dict(r) for r in keys], bank_accounts=[{c.name:getattr(a,c.name) for c in BankAccount.__table__.columns} for a in accounts_list],
                sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.receber,args.pagar)})
            with gzip.open(backup, 'xt', encoding='utf-8') as stream:
                json.dump(snapshot, stream, ensure_ascii=False, default=str)
            with gzip.open(backup, 'rt', encoding='utf-8') as stream:
                if len(json.load(stream)['financial_entries']) != len(old):
                    raise ValueError('Falha na verificação do backup.')
            print('Backup verified:',backup,flush=True)
            for name in sorted(missing_methods):
                method = PaymentMethod(nome=name, tipo='OUTRO')
                db.session.add(method)
                db.session.flush()
                methods[normalize(name)] = method.id
            payloads=[]
            for record in records:
                data=record['payload']
                data['payment_method_id']=methods.get(normalize(record['method']))
                data['bank_account_id']=accounts[normalize(record['account'])].id if record['account'] else None
                match=re.match(r'ordemdeservico(\d+)', normalize(data['descricao'])) if data['entry_type']=='RECEBER' else None
                if match and match.group(1) in orders:
                    order = orders[match.group(1)]
                    data['reference_type']='OS'
                    data['reference_id']=order.id
                    data['descricao']=work_order_receivable_description(
                        order,
                        data.get('installment_number', 1),
                        data.get('installment_total', 1),
                    )
                payloads.append(data)
            db.session.execute(delete(BankReconciliation).where(BankReconciliation.financial_entry_id.in_([r['id'] for r in old])))
            db.session.execute(delete(FinancialEntry).where(FinancialEntry.entry_type.in_(['PAGAR','RECEBER'])))
            db.session.execute(delete(MigrationKey).where(MigrationKey.migration_id.in_(select(DataMigration.id).where(DataMigration.entity.in_(['pagar','receber'])))))
            # Group optional timestamps so bulk inserts preserve each source date.
            groups={}
            for payload in payloads:
                groups.setdefault(tuple(sorted(payload)),[]).append(payload)
            for group in groups.values():
                for start in range(0,len(group),500):
                    db.session.execute(insert(FinancialEntry.__table__),group[start:start+500])
            accounts['juridica'].saldo_atual=Decimal('8469.88')
            accounts['dinheiro'].saldo_atual=Decimal('13946.23')
            db.session.add(AuditEvent(action='SUBSTITUICAO_FINANCEIRO',entity_type='FinancialEntry',
                details=json.dumps({'backup':str(backup),'removed':len(old),'inserted':len(payloads),
                    'balances':{'JURIDICA':'8469.88','DINHEIRO':'13946.23'}})))
            db.session.commit()
            print('COMMITTED',len(payloads),'entries; balances:',str(accounts['juridica'].saldo_atual),str(accounts['dinheiro'].saldo_atual),flush=True)
        except Exception:
            db.session.rollback()
            raise


if __name__ == '__main__':
    main()
