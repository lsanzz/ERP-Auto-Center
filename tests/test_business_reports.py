import unittest
from datetime import date
from decimal import Decimal

from sqlalchemy.pool import StaticPool

from app import create_app
from app.business_reports import report_data
from app.models import Client, FinancialEntry, FiscalDocument, User, db
from app.operations.models import AuditEvent


class BusinessReportsTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'APP_ENV': 'testing', 'AUTO_CREATE_SCHEMA': True,
            'SECRET_KEY': 'business-tests', 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
            'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': StaticPool}})
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.user = User(username='owner', nome='Responsável', role='ADMINISTRADOR')
        self.user.set_password('test')
        db.session.add(self.user)
        db.session.commit()
        self.browser = self.app.test_client()
        with self.browser.session_transaction() as session:
            session['user_id'] = self.user.id
        self.today = date.today()
        self.args = f'start={self.today}&end={self.today}'

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def entry(self, **overrides):
        values = dict(entry_type='RECEBER', descricao='Serviço', valor=100, vencimento=self.today,
            competence_on=self.today, issued_on=self.today, status='PENDENTE')
        values.update(overrides)
        entry = FinancialEntry(**values)
        db.session.add(entry)
        db.session.commit()
        return entry

    def test_cash_and_accrual_do_not_mix(self):
        self.entry(status='RECEBIDO', payment_receipt_at=self.today, taxa=3, juros=5, desconto=2)
        self.entry(valor=40)
        self.entry(entry_type='PAGAR', valor=20, status='PAGO', payment_receipt_at=self.today)
        self.entry(valor=999, status='CANCELADO')
        accrual = report_data(self.today, self.today)
        cash = report_data(self.today, self.today, 'caixa')
        self.assertEqual(accrual['result'], Decimal('120'))
        self.assertEqual(cash['result'], Decimal('80'))
        self.assertEqual(cash['days'][0]['accumulated'], cash['result'])

    def test_views_and_exports_render(self):
        self.entry(categoria='=HYPERLINK("bad")')
        for path in ['/financeiro/balancete', '/financeiro/calendario', '/historico', '/fiscal']:
            response = self.browser.get(path)
            self.assertEqual(response.status_code, 200, path)
        response = self.browser.get('/financeiro/balancete?' + self.args + '&export=csv')
        self.assertEqual(response.status_code, 200)
        self.assertIn("'=HYPERLINK", response.get_data(as_text=True))
        self.assertIn('attachment', response.headers['Content-Disposition'])

    def test_invalid_periods_are_rejected(self):
        for args in ['start=bad', 'start=2026-09-10&end=2026-09-01', 'start=2020-01-01&end=2026-01-01']:
            self.assertEqual(self.browser.get('/financeiro/balancete?' + args).status_code, 400)
        self.assertEqual(self.browser.get('/financeiro/calendario?month=bad').status_code, 400)

    def test_calendar_only_pending_and_links_match_date(self):
        self.entry(descricao='Receber')
        self.entry(entry_type='PAGAR', valor=25)
        self.entry(status='RECEBIDO', valor=800, payment_receipt_at=self.today)
        text = self.browser.get('/financeiro/calendario').get_data(as_text=True)
        self.assertIn('A receber · 1', text)
        self.assertIn('A pagar · 1', text)
        self.assertIn('start_date=' + self.today.isoformat(), text)
        self.assertNotIn('800,00', text)

    def test_audit_created_id_and_rollback(self):
        client = Client(nome='Cliente pesquisável')
        db.session.add(client)
        db.session.commit()
        event = AuditEvent.query.filter_by(entity_type='CLIENT', action='CRIAR', entity_id=client.id).one()
        self.assertIn('nome', event.details)
        client.nome = 'Alteração descartada'
        db.session.flush()
        db.session.rollback()
        self.assertEqual(AuditEvent.query.filter_by(entity_type='CLIENT', action='ALTERAR').count(), 0)
        response = self.browser.get('/historico?' + self.args + '&kind=clientes&q=pesquisável')
        self.assertIn('Cliente pesquisável', response.get_data(as_text=True))

    def test_history_pagination_preserves_filter(self):
        for i in range(45):
            db.session.add(AuditEvent(action='TESTAR', entity_type='EXEMPLO', entity_id=i))
        db.session.commit()
        response = self.browser.get('/historico?' + self.args + '&q=EXEMPLO')
        self.assertIn('45 registro(s)', response.get_data(as_text=True))
        self.assertIn('page=2', response.get_data(as_text=True))
        export = self.browser.get('/historico?' + self.args + '&q=EXEMPLO&export=csv')
        self.assertEqual(export.get_data(as_text=True).count('TESTAR'), 45)

    def test_receipt_requires_settled_receivable(self):
        entry = self.entry()
        self.assertEqual(self.browser.get(f'/financeiro/{entry.id}/recibo').status_code, 400)
        entry.status = 'RECEBIDO'
        entry.payment_receipt_at = self.today
        db.session.commit()
        response = self.browser.get(f'/financeiro/{entry.id}/recibo')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Não substitui nota fiscal', response.get_data(as_text=True))

    def test_restricted_users_and_anonymous(self):
        self.user.role = 'MECANICO'
        db.session.commit()
        for path in ['/financeiro/balancete', '/financeiro/calendario', '/historico', '/fiscal']:
            self.assertEqual(self.browser.get(path).status_code, 403, path)
        self.user.role = 'FINANCEIRO'
        db.session.commit()
        self.assertEqual(self.browser.get('/financeiro/balancete').status_code, 200)
        self.assertEqual(self.browser.get('/historico').status_code, 403)
        self.assertEqual(self.app.test_client().get('/historico').status_code, 302)

    def test_fiscal_filters_do_not_expose_payload(self):
        db.session.add(FiscalDocument(document_type='NFE', status='ERRO', numero='123', request_payload='PRIVATE-PAYLOAD'))
        db.session.commit()
        response = self.browser.get('/fiscal?' + self.args + '&q=123&status=ERRO')
        self.assertEqual(response.status_code, 200)
        self.assertIn('1 documento(s)', response.get_data(as_text=True))
        self.assertNotIn('PRIVATE-PAYLOAD', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
