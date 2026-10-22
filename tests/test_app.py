import unittest
import io
import json
from datetime import date
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from flask import Flask

from app import create_app
from app.models import BankAccount, BankTransaction, FinancialEntry, PaymentMethod, WorkOrder, db
from app.security import configure_security
from app.seeds import seed_database
from flask.testing import FlaskClient


class SessionClient(FlaskClient):
    """Exercise the real CSRF protocol rather than disabling the protection."""
    def open(self, *args, **kwargs):
        if kwargs.get('method', 'GET').upper() in {'POST', 'PATCH', 'PUT', 'DELETE'}:
            token = super().open('/api/csrf').get_json()['csrf_token']
            kwargs['headers'] = {**kwargs.get('headers', {}), 'X-CSRFToken': token}
        return super().open(*args, **kwargs)


class ERPAppTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                'TESTING': True,
                'APP_ENV': 'testing',
                'AUTO_CREATE_SCHEMA': True,
                'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                'SQLALCHEMY_ENGINE_OPTIONS': {
                    'connect_args': {'check_same_thread': False},
                    'poolclass': StaticPool,
                },
            }
        )
        with self.app.app_context():
            seed_database()
        self.app.test_client_class = SessionClient
        self.client = self.app.test_client()


    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login_api(self, username='admin', password='admin123'):
        return self.client.post('/api/session', json={'username': username, 'password': password})

    def login_web(self, username='admin', password='admin123'):
        return self.client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)

    def test_custom_404_page(self):
        response = self.client.get('/pagina-que-nao-existe')
        self.assertEqual(response.status_code, 404)
        self.assertIn('Essa página saiu da rota.'.encode(), response.data)
        self.assertIn('Ir para o início'.encode(), response.data)

    def test_development_trusts_local_hosts(self):
        app = Flask(__name__)
        app.config.update(
            APP_ENV='development',
            TRUSTED_HOSTS='erp.exemplo.com',
            SECRET_KEY='test-secret',
            TESTING=False,
        )
        configure_security(app)
        self.assertIn('localhost', app.config['TRUSTED_HOSTS'])
        self.assertIn('127.0.0.1', app.config['TRUSTED_HOSTS'])

    def test_web_login_and_admin_dashboard(self):
        response = self.login_web()
        self.assertEqual(response.status_code, 200)
        self.assertIn('Seu dia na oficina'.encode(), response.data)
        self.assertIn('Agenda de hoje'.encode(), response.data)
        self.assertIn('Visão financeira'.encode(), response.data)
        self.assertIn('Contas bancárias'.encode(), response.data)
        self.assertIn('Saldo disponível'.encode(), response.data)

    def test_removing_bank_account_with_entries_preserves_history(self):
        self.login_web()
        with self.app.app_context():
            account = BankAccount(nome='Conta com histórico', saldo_inicial=100, saldo_atual=100)
            db.session.add(account)
            db.session.flush()
            entry = FinancialEntry(
                entry_type='RECEBER',
                descricao='Recebimento preservado',
                valor=100,
                vencimento=date.today(),
                status='LIQUIDADO',
                bank_account_id=account.id,
            )
            db.session.add(entry)
            db.session.commit()
            account_id = account.id
            entry_id = entry.id

        response = self.client.post(
            f'/contas-bancarias/{account_id}/remover',
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('histórico financeiro foi preservado'.encode(), response.data)
        self.assertNotIn('Conta com histórico'.encode(), response.data)
        with self.app.app_context():
            account = db.session.get(BankAccount, account_id)
            self.assertIsNotNone(account)
            self.assertFalse(account.ativo)
            self.assertEqual(db.session.get(FinancialEntry, entry_id).bank_account_id, account_id)

    def test_removing_unused_bank_account_deletes_it(self):
        self.login_web()
        with self.app.app_context():
            account = BankAccount(nome='Conta sem uso', saldo_inicial=0, saldo_atual=0)
            db.session.add(account)
            db.session.commit()
            account_id = account.id

        response = self.client.post(
            f'/contas-bancarias/{account_id}/remover',
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('Conta bancária removida.'.encode(), response.data)
        with self.app.app_context():
            self.assertIsNone(db.session.get(BankAccount, account_id))

    def test_api_removing_account_with_bank_transactions_preserves_history(self):
        self.login_api()
        with self.app.app_context():
            account = BankAccount(nome='Conta conciliada', saldo_inicial=50, saldo_atual=50)
            db.session.add(account)
            db.session.flush()
            transaction = BankTransaction(
                bank_account_id=account.id,
                posted_on=date.today(),
                description='Movimentação importada',
                amount=50,
            )
            db.session.add(transaction)
            db.session.commit()
            account_id = account.id
            transaction_id = transaction.id

        response = self.client.delete(f'/api/contas-bancarias/{account_id}')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['history_preserved'])
        with self.app.app_context():
            account = db.session.get(BankAccount, account_id)
            self.assertFalse(account.ativo)
            self.assertEqual(db.session.get(BankTransaction, transaction_id).bank_account_id, account_id)
    def test_login_uses_turnstile_widget_instead_of_visible_otp(self):
        self.app.config.update(TURNSTILE_ENABLED=True, TURNSTILE_SITE_KEY='site-test')
        response = self.client.get('/login')
        self.assertIn(b'cf-turnstile', response.data)
        self.assertIn(b'site-test', response.data)
        self.assertNotIn(b'name="otp"', response.data)

    @patch('app.security.urlrequest.urlopen')
    def test_turnstile_is_validated_on_server(self, mocked_open):
        from app.security import verify_turnstile
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self): return json.dumps({'success': True, 'action': 'login'}).encode()
        mocked_open.return_value = FakeResponse()
        self.app.config.update(TURNSTILE_ENABLED=True, TURNSTILE_SECRET_KEY='secret-test')
        with self.app.app_context():
            self.assertTrue(verify_turnstile('valid-token', '127.0.0.1'))
            self.assertFalse(verify_turnstile('', '127.0.0.1'))
        body = mocked_open.call_args.args[0].data.decode()
        self.assertIn('secret=secret-test', body)
        self.assertIn('response=valid-token', body)

    def test_mfa_is_requested_only_after_password(self):
        import pyotp
        from app.models import User
        from app.security import encrypt_secret
        secret = pyotp.random_base32()
        with self.app.app_context():
            user = User.query.filter_by(username='admin').one()
            user.mfa_enabled = True
            user.mfa_secret_encrypted = encrypt_secret(secret)
            db.session.commit()
        response = self.client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
        self.assertIn('Confirme seu acesso'.encode(), response.data)
        self.assertNotIn('Seu dia na oficina'.encode(), response.data)
        response = self.client.post('/login/mfa', data={'otp': pyotp.TOTP(secret).now()}, follow_redirects=True)
        self.assertIn('Seu dia na oficina'.encode(), response.data)

    def test_mechanic_dashboard_hides_financial_information(self):
        response = self.login_web('mecanico', 'mecanico123')
        self.assertEqual(response.status_code, 200)
        self.assertIn('O.S. em aberto'.encode(), response.data)
        self.assertNotIn('Financeiro'.encode(), response.data)
        self.assertNotIn('Visão financeira'.encode(), response.data)

    def test_finance_overview_filters_and_web_installments(self):
        self.login_web()
        response = self.client.get('/financeiro?view=overdue&kind=RECEBER')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Novo lançamento'.encode(), response.data)
        self.assertIn('A pagar'.encode(), response.data)
        self.assertIn('A receber'.encode(), response.data)
        self.assertIn('Pagas e recebidas'.encode(), response.data)

        response = self.client.post(
            '/financeiro/novo',
            data={
                'entry_type': 'PAGAR',
                'descricao': 'Compra web parcelada',
                'categoria': 'Fornecedores',
                'valor': '300,00',
                'vencimento': '2026-09-10',
                'installment_count': '3',
                'status': 'PENDENTE',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('3 lançamento(s) financeiro(s) criado(s).'.encode(), response.data)
        with self.app.app_context():
            entries = FinancialEntry.query.filter(
                FinancialEntry.descricao.like('Compra web parcelada%')
            ).order_by(FinancialEntry.installment_number).all()
            self.assertEqual(len(entries), 3)
            self.assertEqual([float(entry.valor) for entry in entries], [100.0, 100.0, 100.0])

    def test_settled_web_entry_uses_default_bank_account(self):
        self.login_web()
        with self.app.app_context():
            account = BankAccount.query.filter_by(nome='Conta Principal').one()
            before = account.saldo_atual
        response = self.client.post(
            '/financeiro/novo',
            data={
                'entry_type': 'RECEBER',
                'descricao': 'Receita sem conta',
                'valor': '150,00',
                'vencimento': '2026-09-10',
                'installment_count': '1',
                'status': 'LIQUIDADO',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            entry = FinancialEntry.query.filter_by(descricao='Receita sem conta').one()
            self.assertEqual(entry.bank_account.nome, 'Conta Principal')
            self.assertEqual(db.session.get(BankAccount, entry.bank_account_id).saldo_atual, before + 150)

    def test_finance_uses_original_work_order_customer_name(self):
        self.login_web()
        with self.app.app_context():
            payment_method = PaymentMethod.query.filter_by(tipo='PIX').first()
            order = WorkOrder(
                client_id=1,
                numero='OS-NOME-ORIGINAL',
                client_nome='CLIENTE ORIGINAL TESTE',
            )
            db.session.add(order)
            db.session.flush()
            db.session.add(FinancialEntry(
                entry_type='RECEBER',
                descricao=f'Ordem de Serviço {order.numero}',
                categoria='Ordens de Serviço',
                valor=250,
                vencimento=date.today(),
                status='PENDENTE',
                payment_method_id=payment_method.id,
                reference_type='OS',
                reference_id=order.id,
            ))
            db.session.commit()
            order_number = order.numero
            payment_method_name = payment_method.nome

        response = self.client.get('/financeiro?q=CLIENTE+ORIGINAL+TESTE')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'CLIENTE ORIGINAL TESTE', response.data)
        self.assertIn('<th>Forma</th>'.encode(), response.data)
        self.assertIn(payment_method_name.encode(), response.data)
        self.assertIn('A receber'.encode(), response.data)
        self.assertIn('A pagar'.encode(), response.data)
        self.assertNotIn(b'<span>Vencidas</span>', response.data)
        self.assertNotIn(f'Ordem de Serviço {order_number}'.encode(), response.data)

    def test_finance_separates_accounts_receivable_and_payable(self):
        self.login_web()
        with self.app.app_context():
            db.session.add_all([
                FinancialEntry(
                    entry_type='RECEBER', descricao='RECEITA SEPARADA', valor=100,
                    vencimento=date.today(), status='PENDENTE',
                ),
                FinancialEntry(
                    entry_type='PAGAR', descricao='DESPESA SEPARADA', valor=80,
                    vencimento=date.today(), status='PENDENTE',
                ),
            ])
            db.session.commit()

        receivable = self.client.get('/financeiro?kind=RECEBER')
        payable = self.client.get('/financeiro?kind=PAGAR')

        self.assertIn(b'RECEITA SEPARADA', receivable.data)
        self.assertNotIn(b'DESPESA SEPARADA', receivable.data)
        self.assertIn(b'DESPESA SEPARADA', payable.data)
        self.assertNotIn(b'RECEITA SEPARADA', payable.data)

    def test_credit_payment_generates_installments(self):
        self.login_api()
        with self.app.app_context():
            credit = PaymentMethod.query.filter_by(tipo='CREDITO').first()
            self.assertIsNotNone(credit)
            credit_id = credit.id

        create_os = self.client.post(
            '/api/os',
            json={
                'client_id': 1,
                'employee_id': 1,
                'payment_method_id': credit_id,
                'installment_count': 3,
                'placa': 'ABC1D23',
                'veiculo_descricao': 'Onix branco',
                'observacoes': 'Teste de parcelamento',
            },
        )
        self.assertEqual(create_os.status_code, 201)
        work_order_id = create_os.get_json()['id']

        add_service = self.client.post(
            f'/api/os/{work_order_id}/itens',
            json={'item_type': 'SERVICO', 'reference_id': 1, 'quantidade': 1, 'desconto': 0},
        )
        self.assertEqual(add_service.status_code, 201)

        add_part = self.client.post(
            f'/api/os/{work_order_id}/itens',
            json={'item_type': 'PRODUTO', 'reference_id': 1, 'quantidade': 2, 'desconto': 0},
        )
        self.assertEqual(add_part.status_code, 201)

        finish = self.client.post(f'/api/os/{work_order_id}/finalizar')
        self.assertEqual(finish.status_code, 200)
        payload = finish.get_json()
        self.assertEqual(len(payload['financial_entries']), 3)

        with self.app.app_context():
            order = db.session.get(WorkOrder, work_order_id)
            entries = (
                FinancialEntry.query.filter_by(reference_type='OS', reference_id=work_order_id)
                .order_by(FinancialEntry.installment_number.asc())
                .all()
            )
            self.assertEqual(order.status, 'FINALIZADA')
            self.assertEqual(order.employee_id, 1)
            self.assertEqual(order.payment_method_id, credit_id)
            self.assertEqual(order.installment_count, 3)
            self.assertEqual(len(entries), 3)
            self.assertTrue(all(entry.installment_total == 3 for entry in entries))
            self.assertAlmostEqual(sum(float(entry.valor) for entry in entries), float(order.total_geral), places=2)

    def test_create_work_order_with_inline_services_and_parts(self):
        self.login_api()
        response = self.client.post(
            '/api/os',
            json={
                'client_id': 1,
                'employee_id': 1,
                'placa': 'BRA2E19',
                'veiculo_descricao': 'Tracker prata',
                'servicos': [
                    {'descricao': 'Troca de óleo sintético', 'quantidade': 1, 'valor_unitario': 120, 'total': 120},
                    {'descricao': 'Alinhamento técnico', 'quantidade': 1, 'valor_unitario': 90, 'total': 90},
                ],
                'pecas': [
                    {'descricao': 'Filtro de óleo premium', 'quantidade': 1, 'valor_unitario': 35.5, 'total': 35.5},
                ],
            },
        )
        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(len(payload['servicos']), 2)
        self.assertEqual(len(payload['pecas']), 1)
        self.assertAlmostEqual(payload['total_servicos'], 210.0, places=2)
        self.assertAlmostEqual(payload['total_pecas'], 35.5, places=2)
        self.assertAlmostEqual(payload['total_geral'], 245.5, places=2)


    def test_accounts_payable_can_be_created_in_installments(self):
        self.login_api()
        response = self.client.post(
            '/api/financeiro',
            json={
                'entry_type': 'PAGAR',
                'descricao': 'Compra parcelada de peças',
                'categoria': 'Fornecedores',
                'valor': 300,
                'vencimento': '2026-04-12',
                'installment_count': 3,
            },
        )
        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(len(payload), 3)
        self.assertTrue(all(item['installment_total'] == 3 for item in payload))

    def test_xml_import_creates_payable_entry(self):
        self.login_api()
        xml = b'''<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe>
        <infNFe Id="NFe35260414310170001310550050001853871299763660">
        <ide><nNF>185387</nNF><serie>5</serie><dhEmi>2026-04-12T10:00:00-03:00</dhEmi></ide>
        <emit><xNome>Fornecedor Teste</xNome><CNPJ>14310170001310</CNPJ></emit>
        <det nItem="1"><prod><cProd>T1</cProd><xProd>Filtro teste</xProd><qCom>1</qCom><vUnCom>50</vUnCom><vProd>50</vProd></prod></det>
        <total><ICMSTot><vNF>50</vNF></ICMSTot></total>
        </infNFe></NFe></nfeProc>'''
        with io.BytesIO(xml) as fh:
            response = self.client.post(
                '/api/financeiro/importar-xml',
                data={'xml_file': (fh, 'nfe.xml')},
                content_type='multipart/form-data',
            )
        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload['xml']['numero'], '185387')
        self.assertEqual(len(payload['xml']['items']), 1)
        self.assertEqual(payload['financial_entries'][0]['entry_type'], 'PAGAR')

    def test_mechanic_cannot_access_financial_api(self):
        self.login_api('mecanico', 'mecanico123')
        response = self.client.get('/api/financeiro')
        self.assertEqual(response.status_code, 403)

    def test_cnpj_lookup_rejects_cpf(self):
        self.login_api()
        response = self.client.get('/api/clientes/cnpj/12345678901')
        self.assertEqual(response.status_code, 400)
        self.assertIn('CNPJ', response.get_json()['error'])

    @patch('app.api.lookup_cnpj')
    def test_cnpj_lookup_returns_data_for_company(self, mocked_lookup):
        mocked_lookup.return_value = {
            'cpf_cnpj': '11222333000181',
            'nome': 'Empresa Exemplo LTDA',
            'telefone': '11999999999',
            'email': 'contato@empresa.com',
            'endereco': 'Rua Teste, 100',
            'situacao': 'ATIVA',
            'atividade_principal': 'Comércio',
        }
        self.login_api()
        response = self.client.get('/api/clientes/cnpj/11222333000181')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['nome'], 'Empresa Exemplo LTDA')
        self.assertEqual(data['cpf_cnpj'], '11222333000181')


if __name__ == '__main__':
    unittest.main()
