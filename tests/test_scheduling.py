import unittest
from datetime import datetime, timedelta

from app import create_app, _normalize_database_url
from app.models import Client, Employee, User, WorkOrder, db
from app.fleet.models import Vehicle
from app.scheduling.models import Appointment, WorkshopResource, WorkOrderStageHistory
from app.scheduling.services import change_stage, convert_to_work_order, save_appointment


class SchedulingTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'APP_ENV': 'testing', 'AUTO_CREATE_SCHEMA': True,
                               'SECRET_KEY': 'test', 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}})
        self.ctx = self.app.app_context(); self.ctx.push()
        self.user = User(username='agenda', nome='Agenda', role='ADMINISTRADOR'); self.user.set_password('test')
        self.client_model = Client(nome='Cliente Agenda')
        self.employee = Employee(nome='Técnico', funcao='Mecânico')
        self.resource = WorkshopResource(nome='Elevador 1', tipo='ELEVADOR')
        db.session.add_all([self.user, self.client_model, self.employee, self.resource]); db.session.flush()
        self.vehicle = Vehicle(client_id=self.client_model.id, descricao='Uno', placa='ABC1D23')
        db.session.add(self.vehicle); db.session.commit()

    def tearDown(self):
        db.session.remove(); self.ctx.pop()

    def data(self, start=None, end=None):
        start = start or datetime(2026, 9, 8, 8)
        end = end or start + timedelta(hours=1)
        return {'client_id': self.client_model.id, 'vehicle_id': self.vehicle.id,
                'employee_id': self.employee.id, 'resource_id': self.resource.id,
                'start_at': start.isoformat(timespec='minutes'), 'end_at': end.isoformat(timespec='minutes'),
                'servico_previsto': 'Revisão'}

    def test_mysql_url_is_required_and_normalized(self):
        with self.assertRaises(RuntimeError): _normalize_database_url(None, None)
        with self.assertRaises(RuntimeError): _normalize_database_url('postgresql://x:y@localhost/db', None)
        url = _normalize_database_url('mysql://x:y@localhost/db', None)
        self.assertTrue(url.startswith('mysql+pymysql://'))
        self.assertIn('charset=utf8mb4', url)

    def test_overlap_and_conversion_to_work_order(self):
        first = save_appointment(Appointment(), self.data())
        db.session.commit()
        with self.assertRaises(ValueError):
            save_appointment(Appointment(), self.data(datetime(2026, 9, 8, 8, 30), datetime(2026, 9, 8, 9, 30)))
        db.session.rollback()
        order = convert_to_work_order(first, self.user.id)
        db.session.commit()
        self.assertEqual(order.vehicle_id, self.vehicle.id)
        self.assertEqual(order.workshop_resource_id, self.resource.id)
        self.assertEqual(order.current_stage, 'RECEPCAO')
        self.assertEqual(first.status, 'EM_ATENDIMENTO')
        self.assertEqual(WorkOrderStageHistory.query.count(), 1)
        self.assertIs(convert_to_work_order(first, self.user.id), order)

    def test_unassigned_appointments_do_not_conflict(self):
        data = self.data(); data['employee_id'] = ''; data['resource_id'] = ''
        save_appointment(Appointment(), data)
        save_appointment(Appointment(), data)
        db.session.commit()
        self.assertEqual(Appointment.query.count(), 2)

    def test_stage_closes_previous_and_updates_work_order(self):
        order = WorkOrder(client_id=self.client_model.id, numero='OS-STAGE')
        db.session.add(order); db.session.flush()
        change_stage(order, 'RECEPCAO', self.user.id)
        db.session.flush()
        change_stage(order, 'AGUARDANDO_PECA', self.user.id, 'Filtro sem estoque')
        db.session.commit()
        entries = WorkOrderStageHistory.query.order_by(WorkOrderStageHistory.id).all()
        self.assertIsNotNone(entries[0].ended_at)
        self.assertIsNone(entries[1].ended_at)
        self.assertEqual(order.status, 'AGUARDANDO_PECA')
        self.assertEqual(order.blocking_reason, 'Filtro sem estoque')

    def test_pages_and_csrf(self):
        browser = self.app.test_client()
        token = browser.get('/api/csrf').json['csrf_token']
        response = browser.post('/api/session', json={'username': 'agenda', 'password': 'test'}, headers={'X-CSRFToken': token})
        self.assertEqual(response.status_code, 200)
        for path in ('/agenda/', '/agenda/novo', '/agenda/patio', '/agenda/recursos'):
            self.assertEqual(browser.get(path).status_code, 200, path)
        token = browser.get('/api/csrf').json['csrf_token']
        data = {**self.data(), 'csrf_token': token}
        response = browser.post('/agenda/novo', data=data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Revisão'.encode(), response.data)


if __name__ == '__main__': unittest.main()
