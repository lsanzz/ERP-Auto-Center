"""Merge enriched exports without replaying bank balance movements."""
import argparse
import gzip
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import insert, update
from app import create_app
from app.models import BankAccount, FinancialEntry, PaymentMethod, db
from app.data_migration.finance_replace import parse_finance_export
from app.data_migration.service import normalize


def source(value):
    try:
        return {normalize(k): v for k, v in json.loads(value or '{}').items()}
    except (ValueError, AttributeError):
        return {}


def key(payload):
    raw = source(payload.get('observacoes_pagamento'))
    title = raw.get('nomedareceita') or raw.get('nomedadespesa') or payload['descricao']
    return (payload['entry_type'], normalize(title), str(payload['vencimento']), str(payload['valor']),
            normalize(raw.get('formadepagamento', '')))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('pagar', type=Path)
    parser.add_argument('receber', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    records = parse_finance_export(args.pagar, 'PAGAR') + parse_finance_export(args.receber, 'RECEBER')
    app = create_app()
    with app.app_context():
        old = list(db.session.execute(db.select(FinancialEntry.__table__)).mappings())
        lookup = defaultdict(list)
        for row in old:
            lookup[key(row)].append(row)
        methods = defaultdict(list)
        accounts = defaultdict(list)
        for method in PaymentMethod.query.all():
            methods[normalize(method.nome)].append(method.id)
        for account in BankAccount.query.all():
            accounts[normalize(account.nome)].append(account.id)
        changes, additions, ambiguous = [], [], []
        seen = set()
        for record in records:
            payload = record['payload']
            candidates = lookup[key(payload)]
            if not candidates:
                candidates = [r for old_key, rows in lookup.items() if old_key[:4] == key(payload)[:4] for r in rows]
            raw = source(payload['observacoes_pagamento'])
            if len(candidates) > 1:
                for field in ('fornecedor', 'cliente', 'datadecadastro', 'datadeliquidacao'):
                    if raw.get(field):
                        narrowed = [r for r in candidates if source(r['observacoes_pagamento']).get(field) == raw[field]]
                        if narrowed:
                            candidates = narrowed
            if len(candidates) > 1 and raw.get('documento'):
                candidates = [r for r in candidates if source(r['observacoes_pagamento']).get('documento') == raw['documento']]
            candidates = [r for r in candidates if r['id'] not in seen]
            if len(candidates) > 1 and len({r['observacoes_pagamento'] for r in candidates}) == 1:
                candidates = candidates[:1]
            if len(candidates) > 1:
                ambiguous.append(payload['descricao'])
                continue
            for field, mapping, name in [('payment_method_id', methods, record['method']), ('bank_account_id', accounts, record['account'])]:
                matches = mapping[normalize(name)] if name else []
                if name and len(matches) != 1:
                    raise ValueError(f'Cadastro ausente ou ambíguo: {name}')
                payload[field] = matches[0] if matches else None
            if candidates:
                existing = candidates[0]
                if existing['id'] in seen:
                    raise ValueError('Mais de uma linha corresponde à mesma conta.')
                seen.add(existing['id'])
                # Enrich existing entries without overwriting settlements made in this ERP.
                changes.append((existing, payload['observacoes_pagamento']))
            else:
                if raw.get('cliente'):
                    payload['descricao'] = raw['cliente'][:255]
                additions.append(payload)
        print(json.dumps(dict(existing=len(changes), new=len(additions), ambiguous=ambiguous), ensure_ascii=False), flush=True)
        if not args.apply:
            print([(p['descricao'], str(p['vencimento']), str(p['valor']), p['status']) for p in additions])
        if ambiguous:
            raise ValueError('Correspondências ambíguas; nenhuma alteração aplicada.')
        if not args.apply:
            return
        folder = Path(app.instance_path) / 'backups'
        folder.mkdir(parents=True, exist_ok=True)
        backup = folder / f'finance-enrichment-{datetime.now():%Y%m%d-%H%M%S}.json.gz'
        with gzip.open(backup, 'wt', encoding='utf-8') as stream:
            json.dump([dict(row) for row, _ in changes], stream, default=str, ensure_ascii=False)
        with gzip.open(backup, 'rt', encoding='utf-8') as stream:
            assert len(json.load(stream)) == len(changes)
        table = FinancialEntry.__table__
        from sqlalchemy import case
        for start in range(0, len(changes), 200):
            batch = {row['id']: details for row, details in changes[start:start + 200]}
            db.session.execute(update(table).where(table.c.id.in_(batch)).values(
                observacoes_pagamento=case(batch, value=table.c.id), version=table.c.version + 1))
        for payload in additions:
            db.session.execute(insert(table).values(**payload))
        db.session.commit()
        print('Importação concluída. Backup:', backup, flush=True)


if __name__ == '__main__':
    main()
