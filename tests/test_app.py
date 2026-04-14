import unittest
from unittest.mock import patch

from sqlalchemy.pool import StaticPool

from app import create_app
from app.models import FinancialEntry, PaymentMethod, WorkOrder, db


class ERPAppTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                'TESTING': True,
                'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                'SQLALCHEMY_ENGINE_OPTIONS': {
                    'connect_args': {'check_same_thread': False},
                    'poolclass': StaticPool,
                },
            }
        )
        self.client = self.app.test_client()


    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login_api(self, username='admin', password='admin123'):
        return self.client.post('/api/session', json={'username': username, 'password': password})

    def login_web(self, username='admin', password='admin123'):
        return self.client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)

    def test_web_login_and_admin_dashboard(self):
        response = self.login_web()
        self.assertEqual(response.status_code, 200)
        self.assertIn('Painel inicial'.encode(), response.data)
        self.assertIn('Faturamento do dia'.encode(), response.data)

    def test_mechanic_dashboard_hides_financial_information(self):
        response = self.login_web('mecanico', 'mecanico123')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Painel inicial'.encode(), response.data)
        self.assertNotIn('Faturamento do dia'.encode(), response.data)
        self.assertNotIn('Financeiro'.encode(), response.data)

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
        xml_path = '/mnt/data/35260414310170001310550050001853871299763660 (1).xml'
        with open(xml_path, 'rb') as fh:
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
