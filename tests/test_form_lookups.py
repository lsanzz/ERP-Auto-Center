import unittest
from decimal import Decimal

from app import create_app
from app.fleet.models import Vehicle
from app.models import Client, Product, Service, User, db


class FormLookupTest(unittest.TestCase):
    """Forms load clients and catalog items on demand instead of embedding every record."""

    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'SECRET_KEY': 'test-secret',
                               'APP_ENV': 'testing', 'AUTO_CREATE_SCHEMA': True})
        self.ctx = self.app.app_context()
        self.ctx.push()
        admin = User(username='lookupadmin', nome='Admin', role='ADMINISTRADOR', ativo=True)
        admin.set_password('test-password')
        mechanic = User(username='lookupmech', nome='Mecânico', role='MECANICO', ativo=True)
        mechanic.set_password('test-password')
        self.maria = Client(nome='MARIA DA SILVA', telefone='(11) 98888-7777', cpf_cnpj='123.456.789-00')
        others = [Client(nome=f'CLIENTE {i:03d}') for i in range(30)]
        db.session.add_all([admin, mechanic, self.maria, *others,
                            Product(codigo='P1', nome='FILTRO DE OLEO', preco_venda=Decimal('35.90')),
                            Product(codigo='P2', nome='FILTRO INATIVO', preco_venda=Decimal('1'), ativo=False),
                            Service(nome='TROCA DE OLEO', preco_base=Decimal('80'))])
        db.session.flush()
        db.session.add(Vehicle(client_id=self.maria.id, placa='ABC1D23', descricao='GOL'))
        db.session.commit()
        self.client = self.app.test_client()
        self.login('lookupadmin')

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def login(self, username):
        token = self.client.get('/api/csrf').get_json()['csrf_token']
        response = self.client.post('/api/session', json={'username': username, 'password': 'test-password'},
                                    headers={'X-CSRFToken': token})
        self.assertEqual(response.status_code, 200)

    def test_client_lookup_matches_name_phone_and_document(self):
        for term in ('maria', '98888', '456.789'):
            items = self.client.get('/clientes/buscar', query_string={'q': term}).json['items']
            self.assertEqual([item['id'] for item in items], [self.maria.id], term)
        self.assertEqual(items[0]['detalhe'], '(11) 98888-7777 · 123.456.789-00')
        self.assertEqual(len(self.client.get('/clientes/buscar').json['items']), 20)

    def test_catalog_lookup_returns_active_items_with_price(self):
        products = self.client.get('/os/catalogo', query_string={'tipo': 'PECA', 'q': 'filtro'}).json['items']
        self.assertEqual(products, [{'nome': 'FILTRO DE OLEO', 'preco': 35.9}])
        services = self.client.get('/os/catalogo', query_string={'tipo': 'SERVICO', 'q': 'oleo'}).json['items']
        self.assertEqual(services, [{'nome': 'TROCA DE OLEO', 'preco': 80.0}])

    def test_lookups_require_permission(self):
        self.client.post('/logout', headers={'X-CSRFToken': self.client.get('/api/csrf').get_json()['csrf_token']})
        self.client = self.app.test_client()
        self.login('lookupmech')
        self.assertEqual(self.client.get('/clientes/buscar?q=maria').status_code, 403)
        self.assertEqual(self.client.get('/os/catalogo?q=filtro').status_code, 403)

    def test_forms_no_longer_embed_every_client(self):
        for path in ('/os/nova', '/orcamentos/novo', '/agenda/novo', '/relatorios'):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn('data-client-picker', html, path)
            self.assertIn('name="client_id"', html, path)
            self.assertNotIn('CLIENTE 029', html, path)
        self.assertNotIn('FILTRO DE OLEO', self.client.get('/os/nova').get_data(as_text=True))
        self.assertNotIn('GOL', self.client.get('/agenda/novo').get_data(as_text=True))

    def test_report_keeps_selected_client_in_filter(self):
        html = self.client.get(f'/relatorios?client_id={self.maria.id}').get_data(as_text=True)
        self.assertIn(f'value="{self.maria.id}"', html)
        self.assertIn('value="MARIA DA SILVA"', html)


if __name__ == '__main__':
    unittest.main()
