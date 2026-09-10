import unittest
from datetime import date

from sqlalchemy.pool import StaticPool

from app import create_app
from app.fleet.models import Vehicle
from app.models import Budget, Client, Product, User, WorkOrder, db
from app.operations.models import InventoryMovement, ServiceWarranty, StockReservation
from app.operations.services import (
    consume_order_parts,
    create_budget_approval,
    ensure_inspection,
    respond_to_budget_approval,
    reserve_order_parts,
    update_inspection,
)
from app.services import add_work_order_item, finalize_work_order


class OperationsTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True, 'APP_ENV': 'testing', 'AUTO_CREATE_SCHEMA': True,
            'SECRET_KEY': 'operations-test', 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
            'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args': {'check_same_thread': False}, 'poolclass': StaticPool},
        })
        self.ctx = self.app.app_context(); self.ctx.push()
        self.user = User(username='ops', nome='Operacoes', role='ADMINISTRADOR'); self.user.set_password('test')
        self.client_model = Client(nome='Cliente Operacional', telefone='11999999999')
        db.session.add_all([self.user, self.client_model]); db.session.flush()
        self.vehicle = Vehicle(client_id=self.client_model.id, descricao='Hatch 1.0', placa='OPS1A23')
        self.product = Product(codigo='P-OPS', nome='Filtro de oleo', estoque_atual=5, estoque_minimo=1, preco_venda=50)
        db.session.add_all([self.vehicle, self.product]); db.session.flush()
        self.order = WorkOrder(client_id=self.client_model.id, vehicle_id=self.vehicle.id, numero='OS-OPS', placa=self.vehicle.placa)
        self.budget = Budget(client_id=self.client_model.id, vehicle_id=self.vehicle.id, numero='ORC-OPS', total=100)
        db.session.add_all([self.order, self.budget]); db.session.flush()
        add_work_order_item(self.order, 'PECA', self.product.id, 2)
        db.session.commit()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def test_detailed_inspection_requires_every_item(self):
        inspection = ensure_inspection(self.order)
        with self.assertRaises(ValueError):
            update_inspection(inspection, {'complete': '1'}, self.user.id)
        data = {'complete': '1', 'odometer': '45000'}
        for item in inspection.items:
            data[f'condition_{item.id}'] = 'OK'
        update_inspection(inspection, data, self.user.id)
        db.session.commit()
        self.assertEqual(inspection.status, 'CONCLUIDA')
        self.assertEqual(inspection.odometer, 45000)

    def test_external_budget_approval_is_single_use(self):
        approval, token = create_budget_approval(self.budget, self.user.id)
        db.session.commit()
        self.assertNotEqual(approval.token_hash, token)
        respond_to_budget_approval(approval, 'APROVADO', {'name': 'Cliente Operacional', 'confirmation': '1'}, '127.0.0.1', 'test')
        db.session.commit()
        self.assertEqual(self.budget.status, 'APROVADO')
        with self.assertRaises(ValueError):
            respond_to_budget_approval(approval, 'REPROVADO', {'name': 'Outro Nome', 'confirmation': '1'}, None, None)

    def test_public_approval_page_updates_budget(self):
        _approval, token = create_budget_approval(self.budget, self.user.id)
        db.session.commit()
        browser = self.app.test_client()
        self.assertEqual(browser.get(f'/operacao/aprovar/{token}').status_code, 200)
        csrf = browser.get('/api/csrf').get_json()['csrf_token']
        response = browser.post(f'/operacao/aprovar/{token}', data={
            'decision': 'APROVADO', 'name': 'Cliente Operacional', 'confirmation': '1',
        }, headers={'X-CSRFToken': csrf})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Resposta registrada', response.data)
        self.assertEqual(db.session.get(Budget, self.budget.id).status, 'APROVADO')

    def test_stock_reservation_and_ledger(self):
        reservations = reserve_order_parts(self.order)
        db.session.commit()
        self.assertEqual(len(reservations), 1)
        self.assertEqual(StockReservation.query.filter_by(status='ATIVA').count(), 1)
        other = WorkOrder(client_id=self.client_model.id, numero='OS-SEM-SALDO')
        db.session.add(other); db.session.flush()
        add_work_order_item(other, 'PECA', self.product.id, 4)
        with self.assertRaises(ValueError):
            reserve_order_parts(other)
        db.session.rollback()
        self.order = db.session.get(WorkOrder, self.order.id)
        self.product = db.session.get(Product, self.product.id)
        consume_order_parts(self.order, self.user.id)
        db.session.commit()
        self.assertEqual(self.product.estoque_atual, 3)
        movement = InventoryMovement.query.one()
        self.assertEqual(movement.movement_type, 'SAIDA_OS')
        self.assertEqual(movement.quantity, -2)

    def test_finalization_creates_warranty(self):
        finalize_work_order(self.order)
        db.session.commit()
        self.assertEqual(ServiceWarranty.query.count(), 1)
        self.assertGreater(self.order.warranty.ends_at, date.today())

    def test_authenticated_operations_pages(self):
        browser = self.app.test_client()
        with browser.session_transaction() as session:
            session['user_id'] = self.user.id
        for path in (f'/operacao/os/{self.order.id}/inspecao', '/operacao/estoque', '/operacao/auditoria'):
            response = browser.get(path)
            self.assertEqual(response.status_code, 200, path)
        settings = browser.get('/configuracoes')
        self.assertIn(b'Auditoria', settings.data)
        self.assertEqual(browser.get('/operacao/pos-venda').status_code, 404)
        self.assertEqual(browser.get('/operacao/buscar').status_code, 404)


if __name__ == '__main__':
    unittest.main()
