from decimal import Decimal
import unittest

from sqlalchemy.pool import StaticPool

from app import create_app
from app.models import BankAccount, Client, FinancialEntry, PaymentMethod, Product, StockEntry, Supplier, WorkOrder, WorkOrderItem, db
from app.operations.models import InventoryMovement
from app.seeds import seed_database
from app.services import create_financial_entries, default_bank_account_id, settle_financial_entry


class FinanceStockFlowsTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}})
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            seed_database()
            db.session.add_all([BankAccount(nome='JURIDICA', saldo_inicial=0, saldo_atual=Decimal('100')),
                                BankAccount(nome='Dinheiro', saldo_inicial=0, saldo_atual=Decimal('50'))])
            db.session.add(Supplier(nome='Autopeças Teste', ativo=True))
            db.session.commit()

    def login(self):
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})

    def test_cash_goes_to_cash_account_and_others_to_juridica(self):
        with self.app.app_context():
            account = lambda tipo: db.session.get(BankAccount, default_bank_account_id(
                PaymentMethod.query.filter_by(tipo=tipo).first().id)).nome
            self.assertEqual(account('DINHEIRO'), 'Dinheiro')
            self.assertEqual(account('PIX'), 'JURIDICA')
            self.assertEqual(account('CREDITO'), 'JURIDICA')

    def test_settling_without_account_moves_the_default_balance(self):
        with self.app.app_context():
            pix = PaymentMethod.query.filter_by(tipo='PIX').first()
            entry = create_financial_entries('RECEBER', 'Serviço', None, Decimal('30'), '2026-10-20', payment_method_id=pix.id)[0]
            entry.bank_account_id = None  # títulos antigos sem conta
            settle_financial_entry(entry)
            db.session.commit()
            self.assertEqual(BankAccount.query.filter_by(nome='JURIDICA').one().saldo_atual, Decimal('130'))

    def test_stock_entry_adds_balance_and_creates_payable(self):
        self.login()
        with self.app.app_context():
            product = Product.query.first()
            before = product.estoque_atual
            text = f'{product.codigo} · {product.nome}'
            supplier = Supplier.query.filter_by(nome='Autopeças Teste').one().id
            cash = PaymentMethod.query.filter_by(tipo='DINHEIRO').first().id
        response = self.client.post('/operacao/estoque/entrada', data={
            'supplier_id': supplier, 'numero_nota': '123', 'data_entrada': '2026-10-20',
            'produto': [text], 'quantidade': ['3'], 'custo': ['12.50'],
            'gerar_conta': '1', 'vencimento': '2026-10-20', 'installment_count': '1',
            'payment_method_id': cash, 'status': 'LIQUIDADO'}, follow_redirects=True)
        self.assertIn('Entrada lançada'.encode(), response.data)
        with self.app.app_context():
            product = Product.query.filter_by(codigo=text.split(' · ')[0]).one()
            self.assertEqual(product.estoque_atual, before + 3)
            self.assertEqual(product.custo, Decimal('12.50'))
            entry = StockEntry.query.filter_by(numero_nota='123').one()
            self.assertEqual(entry.valor_total, Decimal('37.50'))
            self.assertEqual(InventoryMovement.query.filter_by(movement_type='ENTRADA').count(), 1)
            payable = FinancialEntry.query.filter_by(reference_type='ENTRADA_ESTOQUE', reference_id=entry.id).one()
            self.assertEqual((payable.status, payable.bank_account.nome), ('PAGO', 'Dinheiro'))
            self.assertEqual(BankAccount.query.filter_by(nome='Dinheiro').one().saldo_atual, Decimal('12.50'))

    def test_xml_nota_entry_adds_stock_and_payable(self):
        import base64, io, re
        self.login()
        xml = (b'<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe35260414310170001310550050001853871299763661">'
               b'<ide><nNF>777</nNF><serie>1</serie><dhEmi>2026-10-20T10:00:00-03:00</dhEmi></ide>'
               b'<emit><xNome>Fornecedor XML</xNome><CNPJ>14310170001310</CNPJ></emit>'
               b'<det nItem="1"><prod><cProd>XML1</cProd><xProd>Filtro XML</xProd><uCom>UN</uCom><qCom>2</qCom><vUnCom>25</vUnCom><vProd>50</vProd></prod></det>'
               b'<total><ICMSTot><vNF>50</vNF></ICMSTot></total></infNFe></NFe></nfeProc>')
        page = self.client.post('/produtos/importar-xml/preview', data={'xml_file': (io.BytesIO(xml), 'nfe.xml')},
                                content_type='multipart/form-data').data.decode()
        self.assertIn('Filtro XML', page)
        self.assertIn('name="lancar_contas" value="1" checked', page)
        response = self.client.post('/produtos/importar-xml/confirmar', data={
            'codigo[]': 'XML1', 'nome[]': 'Filtro XML', 'unidade[]': 'UN', 'custo[]': '25', 'preco_venda[]': '40',
            'acao_cadastro[]': 'sim', 'lancar_estoque': '1', 'lancar_contas': '1',
            'raw_xml_b64': base64.b64encode(xml).decode()}, follow_redirects=True)
        self.assertIn('id="stock-entry"', response.data.decode())  # volta para o Estoque
        with self.app.app_context():
            self.assertEqual(Product.query.filter_by(codigo='XML1').one().estoque_atual, Decimal('2'))
            payable = FinancialEntry.query.filter_by(reference_type='XML_NFE').one()
            self.assertEqual((payable.entry_type, payable.valor), ('PAGAR', Decimal('50')))

    def test_reports_split_by_section(self):
        self.login()
        with self.app.app_context():
            product = Product.query.first()
            product.estoque_minimo, product.estoque_atual = Decimal('5'), Decimal('1')
            db.session.commit()
            name = product.nome
        stock = self.client.get('/gestao/?secao=estoque').data.decode()
        self.assertIn('Relatório de estoque', stock)
        self.assertIn(name, stock)  # peça abaixo do mínimo
        self.assertNotIn('Conciliação bancária', stock)
        finance = self.client.get('/gestao/').data.decode()
        self.assertIn('Relatório financeiro', finance)
        self.assertNotIn('Peças no estoque mínimo', finance)
        self.assertIn('Exportar XML das notas', self.client.get('/fiscal').data.decode())

    def test_partial_payment_keeps_rest_open_for_receivable_and_payable(self):
        self.login()
        with self.app.app_context():
            account = BankAccount.query.filter_by(nome='JURIDICA').one().id
            receivable = create_financial_entries('RECEBER', 'Cliente X', 'Serviços', Decimal('100'), '2026-10-30')[0]
            payable = create_financial_entries('PAGAR', 'Fornecedor Y', 'Fornecedores', Decimal('40'), '2026-10-30')[0]
            db.session.commit()
            ids = (receivable.id, payable.id)
        base = {'payment_receipt_at': '2026-10-21', 'bank_account_id': account, 'baixar_conta_presente': '1'}
        self.client.post(f'/financeiro/{ids[0]}/liquidar', data={**base, 'valor_baixa': '30'})          # parcial
        self.client.post(f'/financeiro/{ids[1]}/liquidar', data={**base, 'valor_baixa': '40', 'baixar_conta': '1'})  # quita
        with self.app.app_context():
            rest = db.session.get(FinancialEntry, ids[0])
            self.assertEqual((rest.status, rest.valor, rest.vencimento.isoformat()), ('PENDENTE', Decimal('70.00'), '2026-10-30'))
            part = FinancialEntry.query.filter(FinancialEntry.descricao.like('Cliente X (pagamento parcial)')).one()
            self.assertEqual((part.status, part.valor), ('RECEBIDO', Decimal('30.00')))
            self.assertEqual(db.session.get(FinancialEntry, ids[1]).status, 'PAGO')
            self.assertEqual(BankAccount.query.filter_by(nome='JURIDICA').one().saldo_atual, Decimal('90'))  # 100 + 30 - 40
        response = self.client.post(f'/financeiro/{ids[0]}/liquidar', data={**base, 'valor_baixa': '70'}, follow_redirects=True)
        self.assertIn('menor que o valor em aberto'.encode(), response.data)  # parcial não pode quitar tudo

    def test_finance_page_has_new_entry_popup(self):
        self.login()
        page = self.client.get('/financeiro').data.decode()
        self.assertIn('id="new-entry"', page)
        self.assertIn('data-method-accounts', page)
        self.assertIn('id="stock-entry"', self.client.get('/operacao/estoque').data.decode())


    def test_work_order_page_receives_into_default_account(self):
        self.login()
        with self.app.app_context():
            pix = PaymentMethod.query.filter_by(tipo='PIX').first()
            order = WorkOrder(client_id=Client.query.first().id, numero='T-1', status='FINALIZADA', payment_method_id=pix.id,
                              total_geral=Decimal('80'), client_nome='Fulano')
            db.session.add(order)
            db.session.flush()
            entry = create_financial_entries('RECEBER', 'O.S. T-1', None, Decimal('80'), '2026-10-20', payment_method_id=pix.id,
                                             reference_type='OS', reference_id=order.id)[0]
            db.session.commit()
            order_id, entry_id, account_id = order.id, entry.id, entry.bank_account_id
            self.assertEqual(db.session.get(BankAccount, account_id).nome, 'JURIDICA')
        page = self.client.get(f'/os/{order_id}').data.decode()
        self.assertIn(f'data-open="settle-{entry_id}"', page)
        response = self.client.post(f'/financeiro/{entry_id}/liquidar', data={
            'payment_receipt_at': '2026-10-20', 'bank_account_id': account_id, 'valor_baixa': '80',
            'next': f'/os/{order_id}'})
        self.assertTrue(response.headers['Location'].endswith(f'/os/{order_id}'))
        with self.app.app_context():
            self.assertEqual(db.session.get(BankAccount, account_id).saldo_atual, Decimal('180'))

    def test_cannot_delete_work_order_with_settled_receivable(self):
        self.login()
        with self.app.app_context():
            order = WorkOrder(client_id=Client.query.first().id, numero='T-2', status='FINALIZADA', total_geral=Decimal('10'))
            db.session.add(order)
            db.session.flush()
            create_financial_entries('RECEBER', 'O.S. T-2', None, Decimal('10'), '2026-10-20', status='RECEBIDO',
                                     reference_type='OS', reference_id=order.id)
            db.session.commit()
            order_id = order.id
        self.client.post(f'/os/{order_id}/excluir')
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(WorkOrder, order_id))


    def test_launch_receivables_popup_receives_on_work_order_page(self):
        self.login()
        with self.app.app_context():
            cash = PaymentMethod.query.filter_by(tipo='DINHEIRO').first().id
            order = WorkOrder(client_id=Client.query.first().id, numero='T-3', status='FINALIZADA', total_geral=Decimal('120'),
                              total_servicos=Decimal('120'))
            db.session.add(order)
            db.session.flush()
            db.session.add(WorkOrderItem(work_order_id=order.id, item_type='SERVICO', descricao='Alinhamento',
                                         quantidade=1, valor_unitario=Decimal('120'), desconto=0, total=Decimal('120')))
            db.session.commit()
            order_id = order.id
        page = self.client.get(f'/os/{order_id}').data.decode()
        self.assertIn(f'id="launch-{order_id}"', page)
        response = self.client.post(f'/os/{order_id}/lancar-contas', data={
            'payment_method_id': cash, 'installment_count': '1', 'vencimento': '2026-10-20',
            'receivable_status': 'RECEBIDO', 'payment_receipt_at': '2026-10-20', 'bank_account_id': '',
            'next': f'/os/{order_id}'})
        self.assertTrue(response.headers['Location'].endswith(f'/os/{order_id}'))
        with self.app.app_context():
            entry = FinancialEntry.query.filter_by(reference_type='OS', reference_id=order_id).one()
            self.assertEqual((entry.status, entry.bank_account.nome), ('RECEBIDO', 'Dinheiro'))
            self.assertEqual(BankAccount.query.filter_by(nome='Dinheiro').one().saldo_atual, Decimal('170'))


if __name__ == '__main__':
    unittest.main()
