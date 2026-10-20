from decimal import Decimal
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy.pool import StaticPool

from app import create_app
from app.assistant import llm
from app.models import Client, PaymentMethod, Service, User, WorkOrder, db
from app.seeds import seed_database


class FakeCompletions:
    """Respostas roteirizadas no formato do Groq: cada item é uma lista de chamadas de ferramenta ou um texto final."""

    def __init__(self, script):
        self.script, self.calls = list(script), []

    def create(self, **kwargs):
        self.calls.append({**kwargs, 'messages': list(kwargs['messages'])})
        step = self.script.pop(0)
        number = len(self.calls)
        if isinstance(step, str):
            message = SimpleNamespace(content=step, tool_calls=None)
        else:
            message = SimpleNamespace(content='', tool_calls=[
                SimpleNamespace(id=f'call-{number}-{i}', function=SimpleNamespace(name=name, arguments=json.dumps(args)))
                for i, (name, args) in enumerate(step)])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    def tool_result(self, call_index):
        """Conteúdo do primeiro resultado de ferramenta enviado na chamada `call_index`."""
        return next(m['content'] for m in self.calls[call_index]['messages'] if m['role'] == 'tool')


class AssistantTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}})
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            seed_database()
            db.session.add_all([Client(nome='ELY COROLLA DSP-2E32'), Client(nome='ALEXANDRE BMW'), Client(nome='ALEXANDRE BMW 320')])
            db.session.add(Service(nome='ALINHAMENTO TESTE', preco_base=Decimal('100'), ativo=True))
            db.session.commit()
            self.ely = Client.query.filter_by(nome='ELY COROLLA DSP-2E32').one().id
            self.service = Service.query.filter_by(nome='ALINHAMENTO TESTE').one().id
            self.pix = PaymentMethod.query.filter_by(tipo='PIX').first().id
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})
        env = patch.dict('os.environ', {'GROQ_API_KEY': 'test-key', 'ASSISTANT_ENABLED': ''})
        env.start()
        self.addCleanup(env.stop)

    def send(self, script, text='abre uma O.S.'):
        fake = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(script)))
        with patch.object(llm, 'make_client', return_value=fake):
            response = self.client.post('/assistente/mensagem', json={'texto': text})
        return response, fake.chat.completions

    def os_count(self):
        with self.app.app_context():
            return WorkOrder.query.count()

    def test_proposal_is_not_saved_until_confirmed(self):
        before = self.os_count()
        response, fake = self.send([
            [('buscar_cliente', {'texto': 'ely'})],
            [('propor_os', {'client_id': self.ely, 'placa': 'dsp 2e32',
                            'itens': [{'tipo': 'SERVICO', 'catalogo_id': self.service, 'descricao': 'alinhamento', 'quantidade': 1}],
                            'payment_method_id': self.pix})],
            'Confira o resumo e clique em Confirmar.',
        ])
        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        card = data['cartoes'][0]
        self.assertEqual((card['cliente'], card['placa'], card['total']), ('ELY COROLLA DSP-2E32', 'DSP2E32', 100.0))
        self.assertEqual(self.os_count(), before)
        # Second model call carries the tool result answering the first call.
        self.assertIn('ELY COROLLA', fake.tool_result(1))
        self.assertEqual(fake.calls[1]['messages'][-1]['tool_call_id'], 'call-1-0')

        confirm = self.client.post(f"/assistente/confirmar/{card['draft_id']}")
        self.assertEqual(confirm.status_code, 200, confirm.get_json())
        with self.app.app_context():
            order = WorkOrder.query.filter_by(numero=confirm.get_json()['numero']).one()
            self.assertEqual((order.client_id, order.placa, order.total_geral, order.payment_method_id),
                             (self.ely, 'DSP2E32', Decimal('100.00'), self.pix))
        # A proposta só pode ser usada uma vez.
        self.assertEqual(self.client.post(f"/assistente/confirmar/{card['draft_id']}").status_code, 404)

    def test_ambiguous_client_returns_question_not_draft(self):
        response, fake = self.send([
            [('propor_os', {'cliente_nome': 'alexandre bmw x', 'itens': [{'tipo': 'SERVICO', 'descricao': 'alinhamento'}]})],
            'Qual Alexandre?',
        ])
        self.assertEqual(response.get_json()['cartoes'], [])
        result = fake.tool_result(1)
        self.assertIn('candidatos', result)

    def test_invalid_plate_and_unknown_draft(self):
        response, fake = self.send([
            [('propor_os', {'client_id': self.ely, 'placa': '12', 'itens': [{'tipo': 'SERVICO', 'descricao': 'x', 'valor_unitario': 10}]})],
            'Placa inválida.',
        ])
        self.assertIn('inválida', fake.tool_result(1))
        self.assertEqual(self.client.post('/assistente/confirmar/forjado').status_code, 404)

    def test_finance_report_blocked_for_receptionist(self):
        with self.app.app_context():
            user = User(username='recep', role='RECEPCIONISTA', nome='Recepção')
            user.set_password('recep-pass-123')
            db.session.add(user)
            db.session.commit()
        self.client.post('/logout')
        self.client.post('/login', data={'username': 'recep', 'password': 'recep-pass-123'})
        response, fake = self.send([[('relatorio_periodo', {})], 'Sem acesso.'], 'quanto faturei?')
        self.assertEqual(response.status_code, 200)
        self.assertIn('não tem acesso', fake.tool_result(1))

    def test_admin_report_uses_system_numbers(self):
        response, fake = self.send([[('relatorio_periodo', {'inicio': '2026-10-01', 'fim': '2026-10-31'})], 'ok'], 'resumo do mês')
        self.assertIn('saldo_atual_contas', fake.tool_result(1))

    def test_hidden_without_key_or_when_switched_off(self):
        with patch.dict('os.environ', {'ASSISTANT_ENABLED': '0'}):
            self.assertNotIn('ai-panel', self.client.get('/os').data.decode())
            self.assertEqual(self.client.post('/assistente/mensagem', json={'texto': 'oi'}).status_code, 503)

    def test_missing_key_is_reported(self):
        with patch.dict('os.environ', {'GROQ_API_KEY': ''}):
            response = self.client.post('/assistente/mensagem', json={'texto': 'oi'})
        self.assertEqual(response.status_code, 503)

    def test_provider_quota_error_is_friendly(self):
        boom = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(RuntimeError('429 rate_limit_exceeded')))))
        with patch.object(llm, 'make_client', return_value=boom):
            response = self.client.post('/assistente/mensagem', json={'texto': 'oi'})
        self.assertEqual(response.status_code, 502)
        self.assertIn('Limite gratuito', response.get_json()['erro'])


    def test_edit_open_work_order_after_confirmation(self):
        response, _ = self.send([
            [('propor_os', {'client_id': self.ely, 'itens': [{'tipo': 'SERVICO', 'catalogo_id': self.service, 'descricao': 'x'}]})], 'ok'])
        numero = self.client.post(f"/assistente/confirmar/{response.get_json()['cartoes'][0]['draft_id']}").get_json()['numero']
        response, _ = self.send([
            [('propor_alteracao_os', {'numero': numero, 'adicionar_itens': [{'tipo': 'PECA', 'descricao': 'Bico de roda', 'valor_unitario': 20, 'quantidade': 2}]})],
            'ok'], 'adiciona 2 bicos')
        card = response.get_json()['cartoes'][0]
        self.assertEqual((card['total_antes'], card['total']), (100.0, 140.0))
        with self.app.app_context():
            self.assertEqual(WorkOrder.query.filter_by(numero=numero).one().total_geral, Decimal('100.00'))
        self.assertEqual(self.client.post(f"/assistente/confirmar/{card['draft_id']}").status_code, 200)
        with self.app.app_context():
            order = WorkOrder.query.filter_by(numero=numero).one()
            self.assertEqual((order.total_geral, len(order.items)), (Decimal('140.00'), 2))


    def test_one_call_proposal_resolves_client_and_catalog_by_name(self):
        response, fake = self.send([
            [('propor_os', {'cliente_nome': 'ely', 'itens': [{'tipo': 'SERVICO', 'descricao': 'alinhamento teste'}],
                            'payment_method_id': self.pix})],
            'Confira e confirme.'])
        card = response.get_json()['cartoes'][0]
        self.assertEqual((card['cliente'], card['itens'][0]['descricao'], card['total']), ('ELY COROLLA DSP-2E32', 'ALINHAMENTO TESTE', 100.0))
        self.assertEqual(response.get_json()['tempos'].__len__(), 2)
        self.assertIn('Formas de pagamento', fake.calls[0]['messages'][-1]['content'])


if __name__ == '__main__':
    unittest.main()
