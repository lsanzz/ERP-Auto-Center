"""Regressões da revisão de outubro de 2026."""
from app.models import Client, WorkOrder, db
from app.services import next_number
from tests.test_review_regressions import application, browser_for  # noqa: F401  (fixture)


def test_invalid_numeric_query_returns_400_not_500(application):  # noqa: F811
    browser = browser_for(application)
    response = browser.get('/fiscal/nfe-pecas/nova?product_id=abc')
    assert response.status_code == 400


def test_next_number_uses_highest_existing_number_not_last_row(application):  # noqa: F811
    client = Client(nome='Cliente Numeração')
    db.session.add(client); db.session.flush()
    # Importação antiga deixou números altos; a última linha criada tem número menor.
    db.session.add(WorkOrder(client_id=client.id, numero='OS-00120'))
    db.session.add(WorkOrder(client_id=client.id, numero='OS-00007'))
    db.session.add(WorkOrder(client_id=client.id, numero='LEGADO-XYZ'))
    db.session.commit()
    assert next_number(WorkOrder, 'OS') == 'OS-00121'


def test_next_number_starts_at_one_for_new_prefix(application):  # noqa: F811
    assert next_number(WorkOrder, 'OS') == 'OS-00001'
