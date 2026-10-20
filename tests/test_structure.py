import io
import json
import re
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier

from sqlalchemy import inspect, text
from flask_migrate import upgrade, downgrade

from app import create_app
from app.models import db, Client, CompanyPartner, FiscalApiConfig, ManagedCompany, SystemAdmin, SystemSettings, User, WorkOrder, Budget, Product, FinancialEntry, BankAccount
from app.fiscal import sync_focus_company_certificate
from app.fleet.models import Vehicle, OdometerReading, VehicleOwnershipHistory
from app.fleet.services import save_vehicle, record_odometer, link_vehicle, import_legacy_vehicles
from app.services import (dashboard_data, add_work_order_item, approve_budget, create_work_order_from_budget,
                          deduct_work_order_stock, finalize_work_order, settle_financial_entry, client_history)


class StructureTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'SECRET_KEY': 'test-secret',
                               'APP_ENV': 'testing', 'AUTO_CREATE_SCHEMA': True})
        self.ctx = self.app.app_context()
        self.ctx.push()
        # Enable SQLite FK enforcement so tests exercise relationships realistically.
        db.session.execute(text('PRAGMA foreign_keys=ON'))
        self.admin = User(username='testadmin', nome='Admin', role='ADMINISTRADOR', ativo=True)
        self.admin.set_password('test-password')
        self.mechanic = User(username='testmechanic', nome='Mecânico', role='MECANICO', ativo=True)
        self.mechanic.set_password('test-password')
        self.customer = Client(nome='Cliente de teste')
        self.other = Client(nome='Outro cliente')
        db.session.add_all([self.admin, self.mechanic, self.customer, self.other])
        db.session.commit()
        self.client = self.app.test_client()
        self.login()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def token(self):
        return self.client.get('/api/csrf').get_json()['csrf_token']

    def login(self, username='testadmin'):
        response = self.client.post('/api/session', json={'username': username, 'password': 'test-password'},
                                    headers={'X-CSRFToken': self.token()})
        self.assertEqual(response.status_code, 200, response.data.decode(errors='ignore'))

    def post(self, path, data=None, **kwargs):
        return self.client.post(path, data={**(data or {}), 'csrf_token': self.token()}, **kwargs)

    def vehicle(self, **data):
        vehicle = save_vehicle(Vehicle(), {'client_id': self.customer.id, 'descricao': 'Onix branco',
                               'placa': 'ABC-1D23', **data}, self.admin.id)
        db.session.commit()
        return vehicle

    def test_vehicle_create_search_and_render(self):
        response = self.post('/veiculos/novo', {'client_id': self.customer.id, 'descricao': 'Onix branco',
                                               'placa': 'ABC-1D23', 'quilometragem': '35000'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'ABC1D23', response.data)
        vehicle = Vehicle.query.one()
        self.assertEqual(vehicle.quilometragem, 35000)
        self.assertEqual(VehicleOwnershipHistory.query.count(), 1)
        self.assertEqual(self.client.get('/veiculos/?q=Onix').status_code, 200)
        self.assertEqual(self.client.get(f'/veiculos/buscar?client_id={self.customer.id}').json['items'][0]['id'], vehicle.id)
        self.assertEqual(self.client.get(f'/veiculos/buscar?client_id={self.other.id}').json['items'], [])

    def test_duplicate_invalid_and_missing_owner_are_rejected(self):
        self.vehicle()
        for data in ({'placa': 'ABC1D23'}, {'placa': 'INVALID'}, {'client_id': 99999}):
            response = self.post('/veiculos/novo', {'client_id': self.customer.id, 'descricao': 'Teste', **data})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(Vehicle.query.count(), 1)

    def test_odometer_chronology_and_idempotence(self):
        vehicle = self.vehicle()
        yesterday = date.today() - timedelta(days=1)
        record_odometer(vehicle, 100, self.admin.id, yesterday)
        db.session.flush()
        record_odometer(vehicle, 200, self.admin.id)
        db.session.commit()
        record_odometer(vehicle, 200, self.admin.id)
        db.session.flush()
        self.assertEqual(OdometerReading.query.count(), 2)
        for km, day in ((99, date.today()), (300, yesterday), (-1, yesterday), (200, date.today()+timedelta(days=1))):
            with self.assertRaises(ValueError):
                record_odometer(vehicle, km, self.admin.id, day)
        self.assertEqual(vehicle.quilometragem, 200)

    def test_ownership_transfer_preserves_documents(self):
        vehicle = self.vehicle()
        order = WorkOrder(client_id=self.customer.id, numero='OS-HISTORY', placa='ABC1D23', veiculo_descricao='Descrição original')
        db.session.add(order)
        link_vehicle(order, {'vehicle_id': vehicle.id})
        db.session.commit()
        save_vehicle(vehicle, {'client_id': self.other.id, 'descricao': 'Descrição atualizada'}, self.admin.id)
        db.session.commit()
        self.assertEqual(order.client_id, self.customer.id)
        self.assertEqual(order.veiculo_descricao, 'Onix branco')
        self.assertEqual(VehicleOwnershipHistory.query.count(), 2)
        link_vehicle(order, {'vehicle_id': vehicle.id})
        new_order = WorkOrder(client_id=self.customer.id, numero='OS-INVALID')
        with self.assertRaises(ValueError):
            link_vehicle(new_order, {'vehicle_id': vehicle.id})

    def test_budget_conversion_and_api_vehicle_validation(self):
        vehicle = self.vehicle()
        response = self.client.post('/api/orcamentos', json={'client_id': self.customer.id, 'vehicle_id': vehicle.id}, headers={'X-CSRFToken': self.token()})
        self.assertEqual(response.status_code, 201)
        budget = db.session.get(Budget, response.json['id'])
        approve_budget(budget)
        order = create_work_order_from_budget(budget)
        db.session.commit()
        self.assertEqual(order.vehicle_id, vehicle.id)
        self.assertEqual(order.placa, 'ABC1D23')
        self.assertEqual(len(client_history(self.customer.id)['budgets']), 1)
        response = self.client.post('/api/os', json={'client_id': self.other.id, 'vehicle_id': vehicle.id}, headers={'X-CSRFToken': self.token()})
        self.assertEqual(response.status_code, 400)
        response = self.client.patch(f'/api/os/{order.id}', json={'client_id': self.other.id, 'vehicle_id': vehicle.id}, headers={'X-CSRFToken': self.token()})
        self.assertEqual(response.status_code, 400)

    def test_web_link_and_error(self):
        vehicle = self.vehicle()
        response = self.post('/orcamentos/novo', {'client_id': self.customer.id, 'vehicle_id': vehicle.id}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Budget.query.one().vehicle_id, vehicle.id)
        response = self.post('/orcamentos/novo', {'client_id': self.other.id, 'vehicle_id': vehicle.id})
        self.assertEqual(response.status_code, 400)
        response = self.post('/os/nova', {'client_id': self.customer.id, 'client_nome': self.customer.nome,
                                         'vehicle_id': vehicle.id, 'data_entrada': date.today().isoformat()}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkOrder.query.one().vehicle_id, vehicle.id)

    def test_work_order_form_uses_consistent_entity_autocomplete(self):
        response = self.client.get('/os/nova')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="client-autocomplete"', response.data)
        self.assertIn(b'class="custom-suggestion-item client-suggestion"', response.data)
        self.assertIn(b'type="hidden" name="client_id"', response.data)
        self.assertIn(b'id="vehicle-suggestions"', response.data)
        self.assertNotIn(b'<select name="client_id"', response.data)

    def test_company_profile_sections_and_partners_are_saved(self):
        response = self.post('/configuracoes/empresa', {
            'company_name': 'Oficina Teste', 'trade_name': 'Oficina Teste Ltda',
            'company_document': '12.345.678/0001-90', 'person_type': 'JURIDICA',
            'state_registration_exempt': '1', 'tax_regime': '1',
            'address': 'Rua das Oficinas', 'address_number': '123',
            'neighborhood': 'Centro', 'city': 'Campinas', 'state': 'sp',
            'weekdays_open': '1', 'weekdays_from': '08:00', 'weekdays_to': '18:00',
            'partner_name[]': ['Sócio Um'], 'partner_cpf[]': ['123.456.789-00'],
            'partner_email[]': ['socio@example.com'], 'partner_phone[]': ['11999999999'],
            'partner_birth_date[]': ['1990-01-02'], 'partner_rg[]': ['1234567'],
            'partner_share[]': ['50.00'],
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('<summary>Certificado digital</summary>'.encode(), response.data)
        self.assertIn('Certificado A1 (.pfx ou .p12)'.encode(), response.data)
        settings = SystemSettings.query.one()
        self.assertEqual(settings.company_name, 'Oficina Teste')
        self.assertEqual(settings.state, 'SP')
        self.assertTrue(settings.state_registration_exempt)
        self.assertEqual(settings.neighborhood, 'Centro')
        self.assertFalse(settings.saturday_open)
        partner = CompanyPartner.query.one()
        self.assertEqual(partner.full_name, 'Sócio Um')
        self.assertEqual(partner.birth_date.isoformat(), '1990-01-02')
        self.assertEqual(partner.ownership_percentage, Decimal('50.00'))

    def test_a1_certificate_is_validated_and_only_sent_to_official_focus_host(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, 'Oficina Teste'),
            x509.NameAttribute(ObjectIdentifier('2.16.76.1.3.3'), '12345678000190'),
        ])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                       .public_key(key.public_key()).serial_number(x509.random_serial_number())
                       .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=30))
                       .sign(key, hashes.SHA256()))
        pfx = pkcs12.serialize_key_and_certificates(
            b'oficina', key, certificate, None, serialization.BestAvailableEncryption(b'segredo'),
        )
        settings = SystemSettings(company_name='Oficina Teste', trade_name='Oficina Teste Ltda',
                                  company_document='12.345.678/0001-90', person_type='JURIDICA',
                                  address='Rua Teste', city='Campinas', state='SP')
        config = FiscalApiConfig(provider_name='FOCUSNFE', environment='HOMOLOGACAO',
                                 api_token='token-teste', focus_management_token='token-principal',
                                 focus_company_id='empresa-123')

        db.session.add_all([settings, config])
        db.session.commit()
        with patch('app.company_focus.focus_request', side_effect=[
            [{'id': 'empresa-123', 'cnpj': '12345678000190'}], {'id': 'empresa-123'}
        ]) as focus:
            result = sync_focus_company_certificate(settings, config, pfx, 'segredo')
        sent_payload = focus.call_args.args[3]
        self.assertEqual(focus.call_args.args[1:3], ('/empresa-123', 'PUT'))
        self.assertEqual(sent_payload['senha_certificado'], 'segredo')
        self.assertEqual(sent_payload['cnpj'], '12345678000190')
        self.assertEqual(result['subject'], certificate.subject.rfc4514_string())
        self.assertFalse(hasattr(settings, 'certificate_password'))

    def test_system_admin_has_an_isolated_login_and_company_dashboard(self):
        owner = SystemAdmin(username='owner', display_name='Proprietário')
        owner.set_password('senha-muito-segura')
        db.session.add_all([
            owner,
            FiscalApiConfig(provider_name='FOCUSNFE', focus_management_token='PRIVATE-MASTER'),
            ManagedCompany(focus_company_id='focus-1', document='12345678000190', legal_name='Empresa Um'),
        ])
        db.session.commit()
        page = self.client.get('/configuracoes').data
        self.assertNotIn(b'focus_management_token', page)
        self.assertNotIn(b'PRIVATE-MASTER', page)
        self.app.config['WTF_CSRF_ENABLED'] = False
        isolated = self.app.test_client()
        self.assertEqual(isolated.get('/sistema/admin').status_code, 302)
        isolated.get('/sistema/login')
        response = isolated.post('/sistema/login', data={
            'username': 'owner', 'password': 'senha-muito-segura',
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200, response.data.decode(errors='ignore'))
        self.assertIn('Empresa Um'.encode(), response.data)
        self.assertIn('Integração Focus NFe'.encode(), response.data)
        self.assertNotIn(b'PRIVATE-MASTER', response.data)

    def test_company_onboarding_creates_then_updates_and_preserves_local_data_on_failure(self):
        config = FiscalApiConfig(provider_name='FOCUSNFE', active=True, focus_management_token='master')
        db.session.add(config)
        db.session.commit()
        data = {'company_name': 'Teste', 'trade_name': 'Teste Ltda', 'company_document': '12345678000190',
                'address': 'Rua Teste', 'city': 'Campinas', 'state': 'SP'}
        with patch('app.company_focus.focus_request', side_effect=[[], {'id': 123, 'token_homologacao': 'company-token'}]) as focus:
            self.post('/configuracoes/empresa', data)
        self.assertEqual(focus.call_args.args[2], 'POST')
        self.assertEqual(config.focus_company_id, '123')
        self.assertEqual(config.api_token, 'company-token')
        self.assertEqual(SystemSettings.query.one().focus_sync_status, 'SINCRONIZADA')
        with patch('app.company_focus.focus_request', side_effect=[[{'id': 123, 'cnpj': '12345678000190'}], {'id': 123}]) as focus:
            self.post('/configuracoes/empresa', data)
        self.assertEqual(focus.call_args.args[2], 'PUT')
        with patch('app.company_focus.focus_request', side_effect=ValueError('Serviço indisponível')):
            self.post('/configuracoes/empresa', {**data, 'company_name': 'Novo nome'})
        self.assertEqual(SystemSettings.query.one().company_name, 'Novo nome')
        self.assertEqual(SystemSettings.query.one().focus_sync_status, 'PENDENTE')

    def test_stale_edit_and_permissions(self):
        vehicle = self.vehicle()
        response = self.post(f'/veiculos/{vehicle.id}/editar', {'version': '999', 'client_id': self.customer.id, 'descricao': 'Stale'})
        self.assertEqual(response.status_code, 409)
        self.login('testmechanic')
        response = self.post(f'/veiculos/{vehicle.id}/situacao', {'version': str(vehicle.version)})
        self.assertEqual(response.status_code, 403)
        self.mechanic.ativo = False
        db.session.commit()
        self.assertEqual(self.client.get('/veiculos/').status_code, 302)

    def test_legacy_import_dry_run_and_conflicts(self):
        db.session.add_all([
            Budget(client_id=self.customer.id, numero='ORC-1', placa='ABC-1D23', veiculo_descricao='Onix'),
            WorkOrder(client_id=self.customer.id, numero='OS-1', placa='ABC1D23', veiculo_descricao='Onix'),
            WorkOrder(client_id=self.other.id, numero='OS-2', placa='DEF2G34', veiculo_descricao='Gol'),
            WorkOrder(client_id=self.other.id, numero='OS-3', placa='DEF2G34', veiculo_descricao='Uno'),
        ])
        db.session.commit()
        result = self.app.test_cli_runner().invoke(args=['fleet', 'importar-legado'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(Vehicle.query.count(), 0)
        report = import_legacy_vehicles()
        db.session.commit()
        self.assertEqual(report['criados'], 1)
        self.assertEqual(report['vinculados'], 2)
        self.assertEqual(len(report['conflitos']), 1)
        second = import_legacy_vehicles()
        self.assertEqual(second['criados'], 0)
        self.assertEqual(second['vinculados'], 0)

    def test_dashboard_and_net_cash(self):
        db.session.add(WorkOrder(client_id=self.customer.id, numero='OS-OLD', status='EM_ANDAMENTO', data_entrada=date.today()-timedelta(days=5)))
        db.session.add(FinancialEntry(entry_type='RECEBER', descricao='Teste', valor=100, valor_baixa=80, taxa=5,
                                     status='RECEBIDO', vencimento=date.today(), payment_receipt_at=date.today()))
        db.session.commit()
        data = dashboard_data()
        self.assertEqual(data['os_abertas'], 1)
        self.assertEqual(data['os_andamento'], 1)
        self.assertEqual(data['entradas_hoje'], 0)
        self.assertEqual(data['caixa_diario']['recebidos'], Decimal('75'))
        self.assertEqual(self.client.get('/api/dashboard').status_code, 200)
        self.assertEqual(self.client.get('/dashboard').status_code, 200)

    def test_critical_stock_receivables_flow(self):
        product = Product(codigo='T1', nome='Filtro', preco_venda=50, estoque_atual=10)
        order = WorkOrder(client_id=self.customer.id, numero='OS-FLOW')
        account = BankAccount(nome='Caixa', saldo_atual=0)
        db.session.add_all([product, order, account])
        db.session.flush()
        add_work_order_item(order, 'PECA', product.id, 2)
        entries = finalize_work_order(order)
        deduct_work_order_stock(order)
        db.session.commit()
        self.assertEqual(product.estoque_atual, 8)
        deduct_work_order_stock(order)
        again = finalize_work_order(order)
        self.assertEqual(len(again), 1)
        self.assertEqual(product.estoque_atual, 8)
        settle_financial_entry(entries[0], bank_account_id=account.id)
        db.session.commit()
        self.assertEqual(account.saldo_atual, Decimal('100'))

    def test_csrf_required_and_every_rendered_form_has_token(self):
        self.assertEqual(self.client.post('/veiculos/novo', data={}).status_code, 400)
        self.assertEqual(self.client.post('/api/os', json={}).status_code, 400)
        vehicle = self.vehicle()
        class Forms(HTMLParser):
            def __init__(self):
                super().__init__(); self.forms=[]; self.active=None
            def handle_starttag(self, tag, attrs):
                attrs=dict(attrs)
                if tag=='form':
                    self.active={'post':attrs.get('method','get').lower()=='post','token':False}; self.forms.append(self.active)
                if tag=='input' and self.active is not None and attrs.get('name')=='csrf_token':
                    self.active['token']=bool(attrs.get('value'))
            def handle_endtag(self,tag):
                if tag=='form': self.active=None
        for path in ('/login','/dashboard','/veiculos/novo',f'/veiculos/{vehicle.id}',
                     '/os/nova','/orcamentos/novo','/financeiro','/configuracoes','/produtos'):
            response = self.client.get(path, follow_redirects=True)
            self.assertEqual(response.status_code, 200, path)
            parser=Forms(); parser.feed(response.data.decode())
            for form in parser.forms:
                self.assertTrue(not form['post'] or form['token'], path)


class MigrationsTest(unittest.TestCase):
    def test_empty_database_upgrade_downgrade(self):
        app = create_app({'TESTING':True, 'AUTO_CREATE_SCHEMA':False,
                          'SQLALCHEMY_DATABASE_URI':'sqlite://','SQLALCHEMY_ENGINE_OPTIONS':{}})
        with app.app_context():
            self.assertEqual(inspect(db.engine).get_table_names(), [])
            upgrade()
            self.assertIn('vehicles', inspect(db.engine).get_table_names())
            self.assertIn('vehicle_id', {c['name'] for c in inspect(db.engine).get_columns('work_orders')})
            upgrade()
            result = app.test_cli_runner().invoke(args=['adotar-baseline'])
            self.assertNotEqual(result.exit_code, 0)
            downgrade(revision='base')
            self.assertEqual(inspect(db.engine).get_table_names(), ['alembic_version'])

    def test_additive_legacy_columns_preserve_rows(self):
        app = create_app({'TESTING':True, 'AUTO_CREATE_SCHEMA':False,
                          'SQLALCHEMY_DATABASE_URI':'sqlite://','SQLALCHEMY_ENGINE_OPTIONS':{}})
        from app.fleet.schema import upgrade_legacy_vehicle_links
        with app.app_context():
            with db.engine.begin() as connection:
                connection.execute(text('CREATE TABLE vehicles (id INTEGER PRIMARY KEY)'))
                for table in ('work_orders','budgets'):
                    connection.execute(text(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY, placa VARCHAR(10))'))
                    connection.execute(text(f"INSERT INTO {table} VALUES (1, 'ABC1D23')"))
            upgrade_legacy_vehicle_links()
            upgrade_legacy_vehicle_links()
            self.assertEqual(db.session.execute(text('SELECT placa, vehicle_id FROM work_orders')).one(), ('ABC1D23', None))


if __name__ == '__main__':
    unittest.main()
