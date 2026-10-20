"""Formulário de demonstração da landing (website/app.py)."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('lshub_landing_form_test', ROOT / 'website' / 'app.py')
landing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(landing)

VALID = {'name': 'Ana Teste', 'workshop': 'Oficina Exemplo', 'phone': '(19) 99999-0000', 'email': 'ana@example.com',
         'city': 'Campinas / SP', 'team': '2 a 5 pessoas', 'plan': 'Profissional',
         'challenge': 'Orçamentos se perdem no WhatsApp.', 'privacy': 'accepted'}


@pytest.fixture
def browser(tmp_path, monkeypatch):
    monkeypatch.setattr(landing, 'LEADS_FILE', tmp_path / 'leads.jsonl')
    monkeypatch.delenv('LANDING_TEAM_OPTIONS', raising=False)
    monkeypatch.delenv('LANDING_PLAN_OPTIONS', raising=False)
    landing.app.config.update(TESTING=True, TRUSTED_HOSTS=None)
    return landing.app.test_client()


def page_token(browser):
    html = browser.get('/').get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, 'o formulário precisa enviar csrf_token'
    return html, match.group(1)


def test_form_has_options_even_without_env(browser):
    html, _ = page_token(browser)
    assert '2 a 5 pessoas' in html and 'Profissional' in html


def test_valid_request_is_saved_with_every_field(browser):
    _, token = page_token(browser)
    response = browser.post('/demonstracao', data={**VALID, 'csrf_token': token})
    assert response.status_code == 302 and response.headers['Location'].endswith('/obrigado')
    lead = json.loads(landing.LEADS_FILE.read_text(encoding='utf-8').splitlines()[0])
    assert (lead['company'], lead['city'], lead['message']) == ('Oficina Exemplo', 'Campinas / SP', VALID['challenge'])


def test_missing_csrf_shows_the_form_again(browser):
    response = browser.post('/demonstracao', data=VALID)
    assert response.status_code == 400
    assert 'sessão expirou' in response.get_data(as_text=True)
    assert not landing.LEADS_FILE.exists()


def test_incomplete_request_is_rejected(browser):
    _, token = page_token(browser)
    response = browser.post('/demonstracao', data={**VALID, 'workshop': '', 'privacy': '', 'csrf_token': token})
    body = response.get_data(as_text=True)
    assert response.status_code == 400
    assert 'Informe o nome da oficina.' in body and 'autorizar o contato' in body
    assert not landing.LEADS_FILE.exists()
