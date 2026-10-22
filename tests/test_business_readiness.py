"""Assinatura (carência e bloqueio), LGPD (exportação e anonimização) e suporte."""
from datetime import date, timedelta
import io
import json
import unittest
import zipfile

from sqlalchemy.pool import StaticPool

from app import create_app
from app.models import Client, SystemSettings, WorkOrder, db
from app.operations.models import AuditEvent
from app.seeds import seed_database
from app.subscription import subscription_status


class BusinessReadinessTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'SUPPORT_WHATSAPP': '+55 19 99999-0000',
                               'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}})
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            seed_database()
            client = Client(nome='Maria Silva', cpf_cnpj='12345678909', telefone='19 9999', email='m@x.com', endereco='Rua A')
            db.session.add(client)
            db.session.flush()
            db.session.add(WorkOrder(numero='OS-00001', client_id=client.id, client_nome='Maria Silva'))
            db.session.commit()
            self.client_id = client.id
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})

    def set_paid_until(self, value, suspended=False):
        with self.app.app_context():
            settings = SystemSettings.query.first() or SystemSettings(company_name='Oficina Teste')
            db.session.add(settings)
            settings.subscription_paid_until, settings.subscription_suspended = value, suspended
            db.session.commit()

    def test_status_rules(self):
        settings = SystemSettings(subscription_paid_until=date(2026, 10, 10), subscription_suspended=False)
        self.assertEqual(subscription_status(settings, date(2026, 10, 10)), 'ATIVA')
        self.assertEqual(subscription_status(settings, date(2026, 10, 17)), 'CARENCIA')
        self.assertEqual(subscription_status(settings, date(2026, 10, 18)), 'SUSPENSA')
        self.assertEqual(subscription_status(SystemSettings(subscription_suspended=False), date(2030, 1, 1)), 'ATIVA')

    def test_grace_shows_warning_and_suspension_blocks_but_allows_export(self):
        self.set_paid_until(date.today() - timedelta(days=2))
        self.assertIn('em atraso'.encode(), self.client.get('/dashboard').data)
        self.set_paid_until(date.today() - timedelta(days=30))
        blocked = self.client.get('/os')
        self.assertEqual(blocked.status_code, 402)
        self.assertIn('Assinatura suspensa'.encode(), blocked.data)
        self.assertEqual(self.client.get('/api/dashboard').status_code, 402)
        export = self.client.get('/dados/exportar')
        self.assertEqual(export.status_code, 200)
        names = zipfile.ZipFile(io.BytesIO(export.data)).namelist()
        self.assertIn('clients.csv', names)
        self.set_paid_until(date.today() + timedelta(days=30))
        self.assertEqual(self.client.get('/os').status_code, 200)

    def test_client_export_and_anonymization(self):
        data = json.loads(self.client.get(f'/dados/clientes/{self.client_id}/exportar').data)
        self.assertEqual(data['cliente']['cpf_cnpj'], '12345678909')
        self.assertEqual(len(data['ordens_servico']), 1)
        self.client.post(f'/dados/clientes/{self.client_id}/anonimizar', data={'confirmacao': 'nao'})
        with self.app.app_context():
            self.assertEqual(db.session.get(Client, self.client_id).nome, 'Maria Silva')
        self.client.post(f'/dados/clientes/{self.client_id}/anonimizar', data={'confirmacao': 'anonimizar'})
        with self.app.app_context():
            client = db.session.get(Client, self.client_id)
            self.assertEqual((client.cpf_cnpj, client.telefone, client.email), (None, None, None))
            self.assertTrue(client.nome.startswith('Cliente anonimizado'))
            self.assertEqual(WorkOrder.query.one().client_nome, client.nome)  # histórico mantido
            self.assertEqual(AuditEvent.query.filter_by(action='ANONIMIZAR').count(), 1)

    def test_mechanic_cannot_export_personal_data(self):
        self.client.post('/logout')
        self.client.post('/login', data={'username': 'mecanico', 'password': 'mecanico123'})
        self.assertEqual(self.client.get('/dados/exportar').status_code, 403)
        self.assertEqual(self.client.get(f'/dados/clientes/{self.client_id}/exportar').status_code, 403)

    def test_support_link_in_menu(self):
        self.assertIn(b'wa.me/5519999990000', self.client.get('/dashboard').data)


if __name__ == '__main__':
    unittest.main()
