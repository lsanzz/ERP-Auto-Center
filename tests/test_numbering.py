import unittest

from sqlalchemy.pool import StaticPool

from app import create_app
from app.models import Client, WorkOrder, db
from app.services import next_number


class NumberingTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': StaticPool}})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = Client(nome='X')
        db.session.add(self.client)
        db.session.flush()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def add(self, numero):
        db.session.add(WorkOrder(numero=numero, client_id=self.client.id))
        db.session.flush()

    def test_prefixed_sequence_when_no_imported_numbers(self):
        self.assertEqual(next_number(WorkOrder, 'OS'), 'OS-00001')
        self.add('OS-00007')
        self.assertEqual(next_number(WorkOrder, 'OS'), 'OS-00008')

    def test_imported_plain_numbers_continue(self):
        self.add('8901')
        self.add('3781')
        self.add('OS-00001')
        self.assertEqual(next_number(WorkOrder, 'OS'), '8902')


if __name__ == '__main__':
    unittest.main()
