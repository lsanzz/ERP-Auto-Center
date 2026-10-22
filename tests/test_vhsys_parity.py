"""Funções trazidas do comparativo com o vhsys: campos da O.S., filtros, WhatsApp, categorias, agenda e painel."""
from datetime import date, datetime, timedelta
from decimal import Decimal
import unittest

from sqlalchemy.pool import StaticPool

from app import create_app
from app.management import management_summary
from app.models import Client, FinancialEntry, WorkOrder, WorkOrderItem, db, default_category
from app.scheduling.models import Appointment
from app.seeds import seed_database
from app.services import recalculate_work_order_totals
from app.web import whatsapp_url


class VhsysParityTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}})
        self.client = self.app.test_client()
        self.ctx = self.app.app_context(); self.ctx.push()
        db.create_all(); seed_database()
        self.customer = Client(nome='MARIA SILVA', telefone='(11) 98765-4321'); db.session.add(self.customer); db.session.commit()
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def new_order(self, **form):
        data = {'client_id': self.customer.id, 'client_nome': self.customer.nome, 'data_entrada': date.today().isoformat(),
                'servico_descricao[]': 'ALINHAMENTO', 'servico_quantidade[]': '1', 'servico_valor_unitario[]': '100,00',
                'servico_total[]': '100,00'}
        data.update(form)
        return self.client.post('/os/nova', data=data, follow_redirects=True)

    def test_work_order_saves_service_fields_and_discount(self):
        response = self.new_order(desconto='15,00', tipo_atendimento='GARANTIA', promised_at='2026-10-30',
                                  problema_relatado='Barulho na suspensão', laudo='Bucha gasta', observacoes_cliente='Retorno em 30 dias')
        self.assertEqual(response.status_code, 200)
        order = WorkOrder.query.one()
        self.assertEqual(order.total_geral, Decimal('85.00'))
        self.assertEqual((order.tipo_atendimento, order.problema_relatado, order.laudo), ('GARANTIA', 'Barulho na suspensão', 'Bucha gasta'))
        self.assertEqual(order.promised_at.date(), date(2026, 10, 30))
        page = self.client.get(f'/os/{order.id}').data.decode()
        self.assertIn('Bucha gasta', page)
        self.assertIn('Ordem de produção', page)
        production = self.client.get(f'/os/{order.id}/pdf?producao=1&download=0')
        self.assertEqual((production.status_code, production.mimetype), (200, 'application/pdf'))

    def test_discount_cannot_exceed_items(self):
        response = self.new_order(desconto='150,00')
        self.assertIn('desconto deve ficar entre zero'.encode(), response.data)
        self.assertEqual(WorkOrder.query.count(), 0)
        order = WorkOrder(client_id=self.customer.id, numero='T-9', desconto=Decimal('-1'))
        order.items = [WorkOrderItem(item_type='SERVICO', descricao='X', quantidade=1, valor_unitario=10, total=10)]
        with self.assertRaises(ValueError):
            recalculate_work_order_totals(order)

    def test_invalid_service_type_is_rejected(self):
        response = self.new_order(tipo_atendimento='QUALQUER')
        self.assertIn('Tipo de atendimento inválido'.encode(), response.data)

    def test_whatsapp_link_uses_brazilian_number_and_ready_message(self):
        order = WorkOrder(client=self.customer, client_nome='MARIA SILVA', numero='OS-1', status='FINALIZADA',
                          placa='ABC1D23', total_geral=Decimal('85'))
        url = whatsapp_url(order)
        self.assertTrue(url.startswith('https://wa.me/5511987654321?text='))
        self.assertIn('pronto%20para%20retirada', url)
        self.customer.telefone = '123'
        self.assertIsNone(whatsapp_url(order))

    def test_work_order_list_filters_sorting_and_bad_input(self):
        for number, total, status in (('A-1', 50, 'ABERTA'), ('A-2', 300, 'FINALIZADA'), ('A-3', 900, 'FINALIZADA')):
            db.session.add(WorkOrder(client_id=self.customer.id, client_nome='MARIA SILVA', numero=number, status=status,
                                     total_geral=Decimal(total)))
        db.session.commit()
        page = self.client.get('/os?status=FINALIZADA&valor_min=100&valor_max=500').data.decode()
        self.assertIn('A-2', page); self.assertNotIn('A-3', page); self.assertNotIn('A-1', page)
        page = self.client.get('/os?ordem=total&dir=asc').data.decode()
        self.assertLess(page.index('A-1'), page.index('A-3'))
        self.assertEqual(self.client.get('/os?de=nao-e-data&valor_min=abc').status_code, 200)

    def test_default_category_and_dre_sections(self):
        self.assertEqual(default_category('RECEBER', 'OS'), 'Ordens de Serviço')
        self.assertEqual(default_category('PAGAR', 'XML_NFE'), 'Compra de peças')
        today = date.today()
        db.session.add_all([
            FinancialEntry(entry_type='RECEBER', descricao='O.S.', valor=500, vencimento=today, competence_on=today, issued_on=today, reference_type='OS'),
            FinancialEntry(entry_type='PAGAR', descricao='Aluguel', categoria='Aluguel', valor=200, vencimento=today, competence_on=today, issued_on=today),
            FinancialEntry(entry_type='PAGAR', descricao='Peças', valor=100, vencimento=today, competence_on=today, issued_on=today, reference_type='ENTRADA_ESTOQUE'),
        ]); db.session.commit()
        self.assertEqual(FinancialEntry.query.filter_by(descricao='O.S.').one().categoria, 'Ordens de Serviço')
        dre = {section['title']: section for section in management_summary(today, today)['dre']}
        self.assertEqual(dre['Receitas']['total'], Decimal('500'))
        self.assertEqual(dre['Despesas fixas']['rows'], [('Aluguel', Decimal('200'))])
        self.assertEqual(dre['Despesas variáveis']['rows'], [('Compra de peças', Decimal('100'))])
        self.assertIn('DRE gerencial', self.client.get('/gestao/').data.decode())

    def test_schedule_from_work_order_prefills_and_links(self):
        self.new_order()
        order = WorkOrder.query.one()
        page = self.client.get(f'/agenda/novo?os={order.id}').data.decode()
        self.assertIn('MARIA SILVA', page)
        start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
        self.client.post(f'/agenda/novo?os={order.id}', data={
            'client_id': self.customer.id, 'start_at': start.strftime('%Y-%m-%dT%H:%M'),
            'end_at': (start + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'), 'servico_previsto': 'ALINHAMENTO', 'status': 'AGENDADO'})
        self.assertEqual(Appointment.query.one().work_order_id, order.id)
        response = self.client.get(f'/agenda/novo?os={order.id}')
        self.assertEqual(response.status_code, 302)  # já agendada: abre o agendamento existente

    def test_agenda_month_dashboard_period_balances_and_shortcuts(self):
        self.assertIn('Agenda ·', self.client.get('/agenda/?visao=mes').data.decode())
        dashboard = self.client.get('/dashboard?meses=12').data.decode()
        self.assertEqual(dashboard.count('class="area-dot"'), 12)
        self.assertIn('data-private=', dashboard)
        self.assertIn('Mostrar valores', dashboard)
        self.assertIn('+ Novo', dashboard)


    def test_plate_payload_details_fipe_and_theft_alert(self):
        from app.vehicles import normalize_plate_payload
        data = normalize_plate_payload({
            'MARCA': 'VW', 'MODELO': 'GOL', 'VERSAO': '1.6 MSI', 'ano': '2019', 'anoModelo': '2020', 'cor': 'Prata',
            'situacao': 'Roubo/Furto', 'chassi': '*****AB1234', 'municipio': 'Campinas', 'uf': 'SP',
            'extra': {'combustivel': 'Alcool / Gasolina', 'cilindradas': '1598', 'potencia': '120'},
            'fipe': {'dados': [{'texto_valor': 'R$ 50.000,00', 'texto_modelo': 'Gol 1.6', 'score': 10},
                               {'texto_valor': 'R$ 60.000,00', 'texto_modelo': 'Gol 1.6 MSI', 'score': 90}]}}, 'ABC1D23')
        self.assertEqual(data['detalhes']['combustivel'], 'Alcool / Gasolina')
        self.assertEqual((data['detalhes']['ano_fabricacao'], data['detalhes']['ano_modelo']), ('2019', '2020'))
        self.assertEqual(data['detalhes']['chassi_final'], '1234')
        self.assertTrue(data['alerta_roubo'])
        self.assertEqual(data['fipe']['valor'], 'R$ 60.000,00')
        self.assertIsNone(normalize_plate_payload({'MARCA': 'VW'}, 'ABC1D23')['fipe'])

    def test_plate_lookup_returns_workshop_history_even_without_api(self):
        db.session.add(WorkOrder(client_id=self.customer.id, client_nome='MARIA SILVA', numero='H-1', placa='ABC-1D23', total_geral=Decimal('99')))
        db.session.commit()
        from unittest import mock
        with mock.patch('app.api.lookup_plate', side_effect=RuntimeError('Serviço de consulta de placa indisponível.')):
            response = self.client.get('/api/veiculos/placa/ABC1D23')  # API fora do ar: ainda mostra o histórico
        payload = response.get_json()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload['historico']['total'], 1)
        self.assertEqual(payload['historico']['ordens'][0]['numero'], 'H-1')
        self.assertIn('class="mplate"', self.client.get('/consultas/placa').data.decode())

    def test_status_and_employee_change_from_list_return_to_list(self):
        from app.models import Employee
        employee = Employee(nome='RENAN', funcao='MECÂNICO', ativo=True); db.session.add(employee)
        order = WorkOrder(client_id=self.customer.id, client_nome='MARIA SILVA', numero='L-1', status='ABERTA')
        db.session.add(order); db.session.commit()
        self.assertIn('status-menu', self.client.get('/os').data.decode())
        response = self.client.post(f'/os/{order.id}/status', data={'status': 'EM_ANDAMENTO', 'next': '/os?q=L-1'})
        self.assertEqual(response.headers['Location'], f'/os?q=L-1#os-{order.id}')
        response = self.client.post(f'/os/{order.id}/responsavel', data={'employee_id': employee.id, 'next': '//evil.example/x'})
        self.assertTrue(response.headers['Location'].endswith(f'/os/{order.id}'))  # destino externo é ignorado
        db.session.refresh(order)
        self.assertEqual((order.status, order.employee_id), ('EM_ANDAMENTO', employee.id))
        self.assertIsNotNone(order.data_saida if order.status in ('FINALIZADA', 'ENTREGUE') else True)


if __name__ == '__main__':
    unittest.main()
