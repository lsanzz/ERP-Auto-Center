"""Replace generic O.S. finance descriptions with the original customer name."""
import argparse
from datetime import datetime
import gzip
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import case, update
from sqlalchemy.orm import joinedload

from app import create_app
from app.data_migration.service import normalize
from app.models import FinancialEntry, WorkOrder, db
from app.services import work_order_receivable_description


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Grava as correções após criar e verificar o backup.')
    args = parser.parse_args()
    app = create_app()

    with app.app_context():
        entries = (
            FinancialEntry.query
            .filter_by(reference_type='OS')
            .order_by(FinancialEntry.id)
            .all()
        )
        order_ids = {entry.reference_id for entry in entries if entry.reference_id}
        orders = {
            order.id: order
            for order in WorkOrder.query.options(joinedload(WorkOrder.client)).filter(WorkOrder.id.in_(order_ids))
        }
        changes = []
        for entry in entries:
            if not re.match(r'^ordemdeservico\d+', normalize(entry.descricao)):
                continue
            order = orders.get(entry.reference_id)
            if not order:
                continue
            corrected = work_order_receivable_description(
                order,
                entry.installment_number,
                entry.installment_total,
            )
            if corrected == entry.descricao:
                continue
            changes.append({'id': entry.id, 'before': entry.descricao, 'after': corrected})

        print(f'{len(changes)} lançamento(s) para corrigir.', flush=True)
        if not args.apply or not changes:
            db.session.rollback()
            return

        backup_dir = Path(app.instance_path) / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f'finance-os-descriptions-{datetime.now():%Y%m%d-%H%M%S}.json.gz'
        with gzip.open(backup_path, 'wt', encoding='utf-8') as stream:
            json.dump(changes, stream, ensure_ascii=False)
        with gzip.open(backup_path, 'rt', encoding='utf-8') as stream:
            if len(json.load(stream)) != len(changes):
                raise RuntimeError('Falha ao verificar o backup das descrições.')

        changes_by_id = {change['id']: change['after'] for change in changes}
        table = FinancialEntry.__table__
        items = list(changes_by_id.items())
        for start in range(0, len(items), 250):
            batch = dict(items[start:start + 250])
            db.session.execute(
                update(table)
                .where(table.c.id.in_(batch))
                .values(
                    descricao=case(batch, value=table.c.id),
                    version=table.c.version + 1,
                )
            )
        db.session.commit()
        print(f'Corrigidos {len(changes)} lançamento(s). Backup: {backup_path}', flush=True)


if __name__ == '__main__':
    main()
