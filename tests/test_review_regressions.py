"""Regression coverage for the system review, using an isolated database."""
from datetime import date
from decimal import Decimal
import json

import pytest
from flask import g

from app import create_app
from app.auth import safe_next_url
from app.cnpj import lookup_cnpj
from app.models import BankAccount, Client, FinancialEntry, User, WorkOrder, db
from app.operations.models import InspectionPhoto
from app.services import settle_financial_entry, update_work_order_receivables
from app.utils import parse_decimal
from app.xml_import import parse_nfe_xml


@pytest.fixture
def application(tmp_path):
    app = create_app({'TESTING': True, 'APP_ENV': 'testing', 'AUTO_CREATE_SCHEMA': True,
                      'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'SQLALCHEMY_ENGINE_OPTIONS': {}})
    app.instance_path = str(tmp_path)
    with app.app_context():
        user = User(username='review', nome='Revisão', role='ADMINISTRADOR')
        user.set_password('test')
        db.session.add(user)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def browser_for(app, role='ADMINISTRADOR'):
    g.pop('csrf_token', None)
    user = User.query.filter_by(username='review').one()
    user.role = role
    db.session.commit()
    browser = app.test_client()
    with browser.session_transaction() as session:
        session['user_id'] = user.id
    return browser


def post(browser, path, **kwargs):
    token = browser.get('/api/csrf').get_json()['csrf_token']
    return browser.post(path, headers={'X-CSRFToken': token}, **kwargs)


@pytest.mark.parametrize('value', ['NaN', 'sNaN', 'Infinity', '-Infinity', Decimal('NaN'), float('inf')])
def test_nonfinite_amounts_are_rejected(value):
    with pytest.raises(ValueError):
        parse_decimal(value)


@pytest.mark.parametrize('value', [[], ['x'], None, True, 'text', 42])
def test_api_requires_json_object(application, value):
    browser = browser_for(application)
    response = post(browser, '/api/clientes', data=json.dumps(value), content_type='application/json')
    assert response.status_code == 400
    assert Client.query.count() == 0


@pytest.mark.parametrize('entry_type, expected', [('RECEBER', '150'), ('PAGAR', '-50')])
def test_settlement_is_idempotent(application, entry_type, expected):
    account = BankAccount(nome='Banco', saldo_atual=50)
    entry = FinancialEntry(entry_type=entry_type, descricao='Teste', valor=100, vencimento=date.today())
    db.session.add_all([account, entry])
    db.session.commit()
    settle_financial_entry(entry, bank_account_id=account.id)
    db.session.commit()
    settle_financial_entry(entry, bank_account_id=account.id, valor_baixa=500)
    db.session.commit()
    assert account.saldo_atual == Decimal(expected)
    assert entry.valor_baixa == Decimal('100')


@pytest.mark.parametrize('values', [{'valor_baixa': '-1'}, {'taxa': '101'}, {'valor_baixa': 'NaN'},
                                   {'bank_account_id': 999}, {'valor_baixa': 'abc'}])
def test_invalid_settlement_rolls_back(application, values):
    entry = FinancialEntry(entry_type='RECEBER', descricao='Teste', valor=100, vencimento=date.today())
    db.session.add(entry)
    db.session.commit()
    browser = browser_for(application)
    response = post(browser, f'/financeiro/{entry.id}/liquidar', data=values)
    assert response.status_code == 302
    db.session.refresh(entry)
    assert entry.status == 'PENDENTE'
    assert entry.valor_baixa is None


def test_inspection_permissions_and_image_upload(application):
    import io
    from PIL import Image
    customer = Client(nome='Cliente')
    order = WorkOrder(client=customer, numero='OS-REVIEW')
    db.session.add(order)
    db.session.commit()
    browser = browser_for(application, 'FINANCEIRO')
    path = f'/operacao/os/{order.id}/inspecao'
    assert browser.get(path).status_code == 403
    assert post(browser, path, data={}).status_code == 403
    browser = browser_for(application, 'MECANICO')
    stream = io.BytesIO()
    Image.new('RGB', (24, 24)).save(stream, 'JPEG')
    stream.seek(0)
    assert post(browser, path + '/fotos', data={'photo': (stream, 'photo.jpg')}).status_code == 302
    photo = InspectionPhoto.query.one()
    assert photo.content_type == 'image/jpeg'
    assert browser.get(f'/operacao/inspecao/fotos/{photo.id}').status_code == 200


def test_reconfirmation_keeps_original_bank_for_reversal(application):
    order = WorkOrder(client=Client(nome='Cliente'), numero='OS-BANK')
    original = BankAccount(nome='Original', saldo_atual=0)
    other = BankAccount(nome='Outra', saldo_atual=0)
    db.session.add_all([order, original, other])
    db.session.flush()
    entry = FinancialEntry(entry_type='RECEBER', descricao='OS', valor=100, vencimento=date.today(),
                           reference_type='OS', reference_id=order.id)
    db.session.add(entry)
    db.session.commit()
    update_work_order_receivables(order, 'RECEBIDO', bank_account_id=original.id)
    db.session.commit()
    update_work_order_receivables(order, 'RECEBIDO', bank_account_id=other.id)
    db.session.commit()
    assert entry.bank_account_id == original.id
    update_work_order_receivables(order, 'PENDENTE')
    db.session.commit()
    assert original.saldo_atual == 0
    assert other.saldo_atual == 0


@pytest.mark.parametrize('path', ['/api/clientes', '/api/orcamentos', '/api/orcamentos/1/aprovar',
                                  '/clientes/novo', '/orcamentos/novo'])
def test_mechanic_cannot_mutate_customers_or_estimates(application, path):
    browser = browser_for(application, 'MECANICO')
    assert post(browser, path, json={'nome': 'Indevido'}).status_code == 403
    assert Client.query.count() == 0


def test_reception_can_create_customer(application):
    browser = browser_for(application, 'RECEPCIONISTA')
    assert post(browser, '/api/clientes', json={'nome': 'Cliente permitido'}).status_code == 201


def test_sensitive_api_reads_and_mutations_follow_role_permissions(application):
    mechanic = browser_for(application, 'MECANICO')
    assert mechanic.get('/api/clientes').status_code == 403
    assert mechanic.get('/api/orcamentos').status_code == 403
    assert mechanic.get('/api/os').status_code == 200
    assert post(mechanic, '/api/os', json={}).status_code == 403

    finance = browser_for(application, 'FINANCEIRO')
    assert finance.get('/dashboard').status_code == 200
    assert finance.get('/clientes').status_code == 403
    assert finance.get('/orcamentos').status_code == 403
    assert finance.get('/os').status_code == 403
    assert finance.get('/veiculos/').status_code == 403

    mechanic = browser_for(application, 'MECANICO')
    assert mechanic.get('/dashboard').status_code == 200
    assert mechanic.get('/clientes').status_code == 403
    assert mechanic.get('/orcamentos').status_code == 403
    assert mechanic.get('/os').status_code == 200
    assert mechanic.get('/veiculos/').status_code == 200
    assert mechanic.get('/agenda/').status_code == 200


def test_customer_list_requires_authentication(application):
    response = application.test_client().get('/clientes')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_vehicle_schedule_order_and_inventory_mutations_are_authorized(application):
    mechanic = browser_for(application, 'MECANICO')
    assert mechanic.get('/veiculos/novo').status_code == 403
    assert mechanic.get('/agenda/novo').status_code == 403
    assert post(mechanic, '/os/nova', data={}).status_code == 403
    assert post(mechanic, '/operacao/os/999/reservar-pecas', data={}).status_code == 403

    reception = browser_for(application, 'RECEPCIONISTA')
    assert reception.get('/veiculos/novo').status_code == 200
    assert reception.get('/agenda/novo').status_code == 200
    assert reception.get('/os/nova').status_code == 200


@pytest.mark.parametrize('candidate', [
    'https://evil.example', '//evil.example', '/\\evil.example', '\\evil.example', 'dashboard', None,
])
def test_post_login_redirect_rejects_external_or_ambiguous_targets(candidate):
    assert safe_next_url(candidate, '/dashboard') == '/dashboard'


def test_logout_clears_pending_authentication_state(application):
    browser = browser_for(application)
    with browser.session_transaction() as session:
        session['pending_login_user_id'] = 999
        session['pending_login_next'] = '/financeiro'
    token = browser.get('/api/csrf').get_json()['csrf_token']
    response = browser.delete('/api/session', headers={'X-CSRFToken': token})
    assert response.status_code == 200
    with browser.session_transaction() as session:
        assert 'user_id' not in session
        assert 'pending_login_user_id' not in session
        assert 'pending_login_next' not in session


def test_cnpja_credential_is_loaded_from_environment(monkeypatch):
    calls = []

    def fake_read(url, headers=None, timeout=10):
        calls.append((url, headers))
        return {'company': {'name': 'Empresa Segura'}, 'taxId': '11222333000181'}

    monkeypatch.setenv('CNPJA_API_KEY', 'segredo-em-variavel')
    monkeypatch.setattr('app.cnpj._read_json', fake_read)
    assert lookup_cnpj('11222333000181')['nome'] == 'Empresa Segura'
    assert calls == [('https://cnpja.com/api/open?cnpj=11222333000181',
                      {'Authorization': 'segredo-em-variavel'})]


def test_xml_import_rejects_entity_expansion():
    malicious = b'''<?xml version="1.0"?>
    <!DOCTYPE x [<!ENTITY a "1234567890"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>
    <nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe><ide>
    <natOp>&b;</natOp></ide></infNFe></NFe></nfeProc>'''
    with pytest.raises(Exception, match='EntitiesForbidden'):
        parse_nfe_xml(malicious)


def test_regular_user_password_policy_requires_twelve_characters(application):
    browser = browser_for(application)
    response = post(browser, '/configuracoes/usuarios/novo', data={
        'username': 'short-password', 'nome': 'Senha Curta', 'password': '123456',
        'role': 'MECANICO', 'ativo': '1',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert User.query.filter_by(username='short-password').first() is None

    response = post(browser, '/configuracoes/usuarios/novo', data={
        'username': 'strong-password', 'nome': 'Senha Forte', 'password': '123456789012',
        'role': 'MECANICO', 'ativo': '1',
    })
    assert response.status_code == 302
    assert User.query.filter_by(username='strong-password').one()


@pytest.mark.parametrize('role', ['RECEPCIONISTA', 'MECANICO', 'ESTOQUISTA', 'FINANCEIRO'])
def test_admin_can_create_every_operational_role(application, role):
    browser = browser_for(application)
    username = role.lower()
    response = post(browser, '/configuracoes/usuarios/novo', data={
        'username': username, 'nome': role.title(), 'password': 'senha-forte-123',
        'role': role, 'ativo': '1',
    })
    assert response.status_code == 302
    assert User.query.filter_by(username=username).one().role == role


def test_landing_sends_defensive_headers():
    from website.app import app as landing

    response = landing.test_client().get('/', base_url='https://lshub.com.br')
    assert response.status_code == 200
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert 'no-store' in response.headers['Cache-Control']
    assert response.headers['Strict-Transport-Security'].startswith('max-age=')


def test_sensitive_pages_are_not_cacheable(application):
    browser = browser_for(application)
    for path in ('/dashboard', '/api/clientes', '/financeiro'):
        assert 'no-store' in browser.get(path).headers['Cache-Control']
    assert 'no-store' not in browser.get('/static/theme.css').headers.get('Cache-Control', '')


@pytest.mark.parametrize('path', [
    '/dashboard', '/clientes', '/clientes/novo', '/produtos', '/produtos/novo',
    '/servicos', '/servicos/novo', '/orcamentos', '/orcamentos/novo', '/os', '/os/nova',
    '/financeiro', '/financeiro/novo', '/financeiro/importacoes', '/financeiro/balancete',
    '/financeiro/calendario', '/fiscal', '/fiscal/nfe-pecas/nova', '/formas-pagamento',
    '/funcionarios', '/relatorios', '/historico', '/configuracoes', '/configuracoes/mfa',
    '/agenda/', '/agenda/novo', '/agenda/patio', '/agenda/recursos', '/veiculos/',
    '/veiculos/novo', '/operacao/estoque', '/operacao/auditoria', '/gestao/',
])
def test_module_pages_render_on_empty_installation(application, path):
    browser = browser_for(application)
    response = browser.get(path, follow_redirects=True)
    assert response.status_code == 200, path
