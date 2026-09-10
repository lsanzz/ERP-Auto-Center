import io
import unittest
from datetime import date
from decimal import Decimal

import pyotp
from PIL import Image
from sqlalchemy.pool import StaticPool

from app import create_app
from app.auth import has_permission
from app.management import create_replenishment_request, import_bank_csv, management_summary, receive_purchase, reverse_inventory_movement
from app.models import BankAccount, BankTransaction, Budget, BudgetItem, Client, FinancialEntry, Product, User, WorkOrder, db
from app.operations.models import InventoryMovement
from app.operations.services import create_budget_approval, respond_to_budget_approval
from app.security import encrypt_secret, verify_totp


class ManagementTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'APP_ENV': 'testing', 'AUTO_CREATE_SCHEMA': True,
            'SECRET_KEY': 'management-tests-secret', 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
            'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args': {'check_same_thread': False}, 'poolclass': StaticPool}})
        self.ctx = self.app.app_context(); self.ctx.push()
        self.admin = User(username='manager', nome='Gerente', role='ADMINISTRADOR'); self.admin.set_password('test')
        self.client_model = Client(nome='Cliente')
        db.session.add_all([self.admin, self.client_model]); db.session.commit()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def test_budget_revision_and_partial_approval_are_immutable(self):
        budget = Budget(client=self.client_model, numero='ORC-MGT', total=Decimal('150'))
        budget.items = [BudgetItem(item_type='SERVICO', descricao='Diagnóstico', total=Decimal('50')),
                        BudgetItem(item_type='PECA', descricao='Peça', total=Decimal('100'))]
        db.session.add(budget); db.session.flush()
        approval, _ = create_budget_approval(budget, self.admin.id)
        respond_to_budget_approval(approval, 'APROVADO', {'name': 'Cliente Teste', 'confirmation': '1',
            f'item_{budget.items[0].id}': 'APROVADO', f'item_{budget.items[1].id}': 'ADIADO'}, '127.0.0.1', 'test')
        self.assertEqual(approval.status, 'APROVADO_PARCIAL')
        self.assertEqual(approval.approved_total, Decimal('50'))
        self.assertIn('Diagnóstico', approval.revision.snapshot_json)

    def test_replenishment_receipt_and_reversal_keep_ledger(self):
        product = Product(codigo='LOW', nome='Filtro', estoque_atual=1, estoque_minimo=5)
        db.session.add(product); db.session.commit()
        purchase = create_replenishment_request(self.admin.id); db.session.flush()
        receive_purchase(purchase, self.admin.id); db.session.flush()
        self.assertEqual(product.estoque_atual, Decimal('10'))
        movement = InventoryMovement.query.filter_by(movement_type='ENTRADA_COMPRA').one()
        reverse_inventory_movement(movement, self.admin.id, 'Recebimento incorreto'); db.session.flush()
        self.assertEqual(product.estoque_atual, Decimal('1'))
        self.assertEqual(InventoryMovement.query.count(), 2)

    def test_financial_summary_csv_import_and_permissions(self):
        account = BankAccount(nome='Conta', saldo_atual=0, saldo_inicial=0)
        db.session.add_all([account, FinancialEntry(entry_type='RECEBER', descricao='Venda', valor=200,
            vencimento=date.today(), competence_on=date.today(), issued_on=date.today()),
            FinancialEntry(entry_type='PAGAR', descricao='Fornecedor', valor=80,
            vencimento=date.today(), competence_on=date.today(), issued_on=date.today())]); db.session.flush()
        summary = management_summary(date.today(), date.today())
        self.assertEqual(summary['result'], Decimal('120'))
        self.assertEqual(summary['expense_ratio'], Decimal('40'))
        self.assertEqual(summary['margin_rate'], Decimal('60'))
        count = import_bank_csv('data;descricao;valor\n09/09/2026;PIX cliente;200,00\n'.encode(), account)
        db.session.flush(); self.assertEqual(count, 1); self.assertEqual(BankTransaction.query.count(), 1)
        stock_user = User(username='stock', nome='Estoque', role='ESTOQUISTA'); stock_user.set_password('test')
        self.assertTrue(has_permission('purchases.manage', stock_user)); self.assertFalse(has_permission('finance.view', stock_user))

    def test_totp_and_real_image_upload(self):
        secret = pyotp.random_base32(); self.admin.mfa_secret_encrypted = encrypt_secret(secret); self.admin.mfa_enabled = True
        self.assertTrue(verify_totp(self.admin, pyotp.TOTP(secret).now()))
        order = WorkOrder(client=self.client_model, numero='OS-IMG'); db.session.add(order); db.session.commit()
        browser = self.app.test_client(); token = browser.get('/api/csrf').get_json()['csrf_token']
        browser.post('/api/session', json={'username': 'manager', 'password': 'test', 'otp': pyotp.TOTP(secret).now()}, headers={'X-CSRFToken': token})
        image_bytes = io.BytesIO(); Image.new('RGB', (20, 20), 'white').save(image_bytes, 'JPEG'); image_bytes.seek(0)
        token = browser.get('/api/csrf').get_json()['csrf_token']
        response = browser.post(f'/operacao/os/{order.id}/inspecao/fotos', data={'photo': (image_bytes, 'test.jpg')},
            headers={'X-CSRFToken': token}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 302)


if __name__ == '__main__':
    unittest.main()
