"""Preenche a categoria dos lançamentos antigos que ficaram sem nenhuma.

Usa a mesma regra dos lançamentos novos (app.models.default_category): O.S. -> "Ordens de Serviço",
nota/entrada de estoque -> "Compra de peças", demais -> "Outras receitas"/"Outras despesas".
Por padrão só mostra a prévia; com --apply grava. Rode pelo "Execute python script" do cPanel
depois do backup do banco.
"""
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from run import app  # noqa: E402
from app.models import FinancialEntry, db, default_category  # noqa: E402


def backfill(apply: bool) -> Counter:
    missing = FinancialEntry.query.filter(db.or_(FinancialEntry.categoria.is_(None), FinancialEntry.categoria == '')).all()
    changes = Counter()
    for entry in missing:
        entry.categoria = default_category(entry.entry_type, entry.reference_type)
        changes[(entry.entry_type, entry.categoria)] += 1
    if apply:
        db.session.commit()
    else:
        db.session.rollback()
    return changes


if __name__ == '__main__':
    apply = '--apply' in sys.argv
    with app.app_context():
        changes = backfill(apply)
        for (kind, category), count in sorted(changes.items()):
            print(f'{kind:8} {category:20} {count}')
        print(f'Total: {sum(changes.values())} lançamento(s) {"atualizados" if apply else "seriam atualizados (prévia; use --apply)"}.')
