"""Regressões da revisão de 22/10/2026: estorno, exclusão, numeração, API e páginas de erro."""
from decimal import Decimal
import time
import unittest

from sqlalchemy.pool import StaticPool

from app import create_app
from app.models import BankAccount, FinancialEntry, PaymentMethod, User, WorkOrder, db
from app.operations.models import AuditEvent
from app.seeds import seed_database
from app.services import create_financial_entries, next_number, settle_partial_financial_entry


class ReviewRegressionTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}})
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            seed_database()
            db.session.add(BankAccount(nome='JURIDICA', saldo_inicial=0, saldo_atual=Decimal('100')))
            db.session.commit()

    def login(self, username='admin', password='admin123'):
        self.client.post('/login', data={'username': username, 'password': password})

    def settled_entry(self) -> int:
        with self.app.app_context():
            pix = PaymentMethod.query.filter_by(tipo='PIX').first()
            entry = create_financial_entries('RECEBER', 'Serviço', None, Decimal('30'), '2026-10-20',
                                             status='RECEBIDO', payment_method_id=pix.id)[0]
            entry.juros, entry.taxa = Decimal('5'), Decimal('2')
            account = db.session.get(BankAccount, entry.bank_account_id)
            account.saldo_atual += Decimal('3')  # líquido creditado = 30 + 5 - 2
            db.session.commit()
            return entry.id

    def balance(self) -> Decimal:
        with self.app.app_context():
            return BankAccount.query.filter_by(nome='JURIDICA').one().saldo_atual

    def test_server_clock_uses_workshop_time_zone(self):
        self.assertEqual(time.tzname[0] in {'-03', 'BRT'}, True, time.tzname)

    def test_revert_returns_net_amount_once_and_is_audited(self):
        entry_id = self.settled_entry()
        self.assertEqual(self.balance(), Decimal('133'))
        self.login()
        self.client.post(f'/financeiro/{entry_id}/estornar')
        self.client.post(f'/financeiro/{entry_id}/estornar')  # clique repetido não devolve de novo
        self.assertEqual(self.balance(), Decimal('100'))
        with self.app.app_context():
            self.assertEqual(db.session.get(FinancialEntry, entry_id).status, 'PENDENTE')
            self.assertEqual(AuditEvent.query.filter_by(action='ESTORNAR', entity_id=entry_id).count(), 1)

    def test_settled_entry_cannot_be_deleted_and_pending_delete_is_audited(self):
        entry_id = self.settled_entry()
        self.login()
        self.client.post(f'/financeiro/{entry_id}/remover')
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(FinancialEntry, entry_id))
        self.client.post(f'/financeiro/{entry_id}/estornar')
        self.client.post(f'/financeiro/{entry_id}/remover')
        with self.app.app_context():
            self.assertIsNone(db.session.get(FinancialEntry, entry_id))
            event = AuditEvent.query.filter_by(action='EXCLUIR', entity_type='FINANCEIRO', entity_id=entry_id).one()
            self.assertIn('Serviço', event.details)
        self.assertEqual(self.balance(), Decimal('100'))

    def test_partial_settlement_twice_keeps_totals(self):
        with self.app.app_context():
            entry = create_financial_entries('RECEBER', 'Parcial', None, Decimal('100'), '2026-10-20')[0]
            settle_partial_financial_entry(entry, '40')
            settle_partial_financial_entry(entry, '40')
            db.session.commit()
            rows = FinancialEntry.query.filter(FinancialEntry.descricao.like('Parcial%')).all()
            self.assertEqual(sum(row.valor for row in rows), Decimal('100'))
            self.assertEqual(entry.valor, Decimal('20'))
            with self.assertRaises(ValueError):
                settle_partial_financial_entry(entry, '20')  # parcial igual ao saldo vira baixa total, não parcial

    def test_next_number_follows_highest_prefixed_and_imported_numbers(self):
        with self.app.app_context():
            client_id = db.session.execute(db.text('SELECT id FROM clients LIMIT 1')).scalar()
            for numero in ('OS-00009', 'OS-00012', 'OS-00010'):
                db.session.add(WorkOrder(numero=numero, client_id=client_id))
            db.session.flush()
            self.assertEqual(next_number(WorkOrder, 'OS'), 'OS-00013')
            db.session.add(WorkOrder(numero='8901', client_id=client_id))
            db.session.flush()
            self.assertEqual(next_number(WorkOrder, 'OS'), '8902')

    def test_finance_api_is_paginated_and_open_to_finance_role(self):
        with self.app.app_context():
            for index in range(3):
                create_financial_entries('PAGAR', f'Conta {index}', None, Decimal('10'), '2026-10-20')
            user = User(username='fin', role='FINANCEIRO', nome='Financeiro')
            user.set_password('financeiro-123')
            db.session.add(user)
            db.session.commit()
        response = self.client.post('/api/session', json={'username': 'fin', 'password': 'financeiro-123'})
        self.assertEqual(response.status_code, 200)
        data = self.client.get('/api/financeiro?per_page=2').get_json()
        self.assertEqual((len(data['items']), data['total'], data['page']), (2, 3, 1))

    def test_mechanic_does_not_see_product_cost(self):
        self.client.post('/api/session', json={'username': 'mecanico', 'password': 'mecanico123'})
        products = self.client.get('/api/produtos').get_json()
        self.assertTrue(products)
        self.assertNotIn('custo', products[0])

    def test_unexpected_error_shows_friendly_page(self):
        self.app.config['PROPAGATE_EXCEPTIONS'] = False

        @self.app.get('/_boom')
        def boom():
            raise RuntimeError('falha')
        response = self.client.get('/_boom')
        self.assertEqual(response.status_code, 500)
        self.assertIn('Algo deu errado'.encode(), response.data)


if __name__ == '__main__':
    unittest.main()
