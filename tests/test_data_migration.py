import io
import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from sqlalchemy import event, select
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from app import create_app
from app.models import (AsyncJob, Client, Employee, FinancialEntry, PaymentMethod, Product, Service, Supplier,
                        User, WorkOrder, WorkOrderStatusHistory, db)
from app.fleet.models import Vehicle
from app.operations.models import InventoryMovement
from app.jobs import run_next_job
from app.data_migration.models import DataMigration, MigrationKey, MigrationRow
from app.data_migration.readers import read_table
from app.data_migration.service import convert, import_batch, parse_decimal


class DataMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'APP_ENV': 'testing', 'AUTO_CREATE_SCHEMA': True,
            'SECRET_KEY': 'migration-test-secret', 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
            'MIGRATION_STORAGE': self.tmp.name,
            'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args': {'check_same_thread': False}, 'poolclass': StaticPool}})
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.admin = User(username='migrate', nome='Admin', role='ADMINISTRADOR')
        self.admin.set_password('test')
        db.session.add(self.admin)
        db.session.commit()
        self.browser = self.app.test_client()
        with self.browser.session_transaction() as session:
            session['user_id'] = self.admin.id
        self.csrf = self.browser.get('/api/csrf').json['csrf_token']

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.tmp.cleanup()

    def post(self, url, data):
        return self.browser.post(url, data=data, headers={'X-CSRFToken': self.csrf})

    def upload(self, data, filename='dados.csv', entity='clientes', **options):
        if isinstance(data, str):
            data = data.encode('utf-8')
        response = self.post('/configuracoes/migracao/enviar', {'files': (io.BytesIO(data), filename),
            'entity': entity, 'source': 'Sistema legado', **options})
        self.assertEqual(response.status_code, 302)
        return db.session.scalar(select(DataMigration).order_by(DataMigration.id.desc()))

    def prepare(self, data, filename='dados.csv', entity='clientes', **options):
        migration = self.upload(data, filename, entity, **options)
        job = run_next_job()
        self.assertEqual(job.status, 'CONCLUIDA', job.last_error)
        self.assertEqual(migration.status, 'PREVIA', migration.last_error)
        return migration

    def confirm(self, migration, **mapping):
        fields = json.loads(migration.mapping_json)
        fields.update(mapping)
        response = self.post(f'/configuracoes/migracao/{migration.id}',
            {**{key: str(value) for key, value in fields.items()}, 'action': 'import', 'confirmed': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(migration.status, 'IMPORTANDO')

    def drain(self):
        for _ in range(30):
            job = run_next_job()
            if job is None:
                break
            self.assertEqual(job.status, 'CONCLUIDA', job.last_error)

    def test_idle_worker_closes_transaction_and_wake_requires_csrf(self):
        self.assertIsNone(run_next_job())
        self.assertFalse(db.session().in_transaction())
        self.assertEqual(self.browser.post('/configuracoes/migracao/processar').status_code, 400)
        with patch('app.data_migration.routes.start_worker') as start:
            self.assertEqual(self.post('/configuracoes/migracao/processar', {}).status_code, 200)
            start.assert_called_once_with(self.app)

    def test_full_finance_replacement_preserves_paid_dates_and_exact_balances(self):
        import runpy
        from app.models import BankAccount
        from app.data_migration.finance_replace import parse_finance_export
        db.session.add_all([BankAccount(nome='JURIDICA', saldo_atual=1), BankAccount(nome='Dinheiro', saldo_atual=2),
            FinancialEntry(entry_type='PAGAR', descricao='Antigo', valor=99, vencimento=date(2026,9,1))])
        db.session.commit()
        header = 'Vencimento;Nome da Receita;Nome da Despesa;Conta Bancária;Forma de Pagamento;Situação;Valor Original;Valor Baixado;Data de Liquidação;Juros;Taxa;Valor Recebido;Valor Pago\n'
        rec = Path(self.tmp.name)/'receber.csv'
        pag = Path(self.tmp.name)/'pagar.csv'
        rec.write_text(header+'01/09/2026;Receita;;JURIDICA;PIX;Pago (02/09/2026);100;100;02/09/2026;0;5;95;0\n',encoding='utf-8')
        pag.write_text(header+'03/09/2026;;Despesa;Dinheiro;;Em Aberto;50;0;;0;0;0;0\n',encoding='utf-8')
        self.assertEqual(parse_finance_export(rec,'RECEBER')[0]['payload']['status'],'RECEBIDO')
        with patch('app.create_app',return_value=self.app), patch.object(self.app,'instance_path',self.tmp.name), patch('sys.argv',
                ['replace',str(rec),str(pag),'--apply']):
            runpy.run_path('scripts/replace_finance_exports.py',run_name='__main__')
        db.session.expire_all()
        entries=FinancialEntry.query.all()
        self.assertEqual(len(entries),2)
        received=next(e for e in entries if e.entry_type=='RECEBER')
        self.assertEqual(received.payment_receipt_at,date(2026,9,2))
        self.assertEqual(received.taxa,Decimal('5'))
        self.assertEqual(BankAccount.query.filter_by(nome='JURIDICA').one().saldo_atual,Decimal('8469.88'))
        self.assertEqual(BankAccount.query.filter_by(nome='Dinheiro').one().saldo_atual,Decimal('13946.23'))
        self.assertEqual(len(list((Path(self.tmp.name)/'backups').glob('*.json.gz'))),1)

    def test_detailed_orders_fill_items_preserve_payment_and_repeat_safely(self):
        from app.data_migration.detailed_orders import complete_orders
        db.session.add(PaymentMethod(nome='PIX', tipo='PIX'))
        migration = self.prepare('OS;Cliente;Data da OS;Valor Serviços;Valor Total;Forma de Pagamento\n'
            '77;Ana GOL ABC1234;14/09/2026;100;100;PIX\n', entity='ordens_servico')
        self.confirm(migration)
        self.drain()
        order = WorkOrder.query.one()
        method = order.payment_method_id
        headers = ['OS','Cliente','Vendedor','Valor Serviços','Valor Produtos','Valor Desconto','Valor Total',
            'Total de parcelas','Data da OS','NF-e Emitida','NFS-e Emitida','Contas','Estoque','Situação','Observações']
        values = ['77','Ana GOL ABC1234','','100','0','0','100','1','14/09/2026','','','','','Atendido','']
        path = Path(self.tmp.name) / 'detail.html'
        path.write_text('<table><tr>' + ''.join('<th>'+h+'</th>' for h in headers) + '</tr><tr data-id="a">' +
            ''.join('<td>'+v+'</td>' for v in values) + '</tr></table>' +
            '<table data-parent="a" data-subtable="true"><tr><td>Alinhamento</td><td>Serviço</td>' +
            '<td>1</td><td>100</td><td>100</td><td>Não</td></tr></table>', encoding='utf-8')
        self.assertEqual(complete_orders(path)[0]['added'], 1)
        self.assertEqual(len(order.items), 0)
        self.assertEqual(complete_orders(path, apply=True)[0]['added'], 1)
        db.session.commit()
        self.assertEqual(len(order.items), 1)
        self.assertEqual(order.items[0].descricao, 'Alinhamento')
        self.assertEqual(order.payment_method_id, method)
        self.assertEqual(complete_orders(path, apply=True)[0]['status'], 'JA_COMPLETA')

    def test_financial_description_and_source_id_are_optional(self):
        for entity in ('receber', 'pagar'):
            migration = self.prepare('Vencimento;Valor\n14/10/2026;100\n', entity=entity)
            self.confirm(migration)
            self.drain()
        entries = FinancialEntry.query.order_by(FinancialEntry.id).all()
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(entry.descricao.startswith('Conta a ') for entry in entries))
        self.assertTrue(all(entry.reference_type == 'MIGRACAO' for entry in entries))

    def test_financial_export_headers_are_mapped_automatically(self):
        migration = self.prepare('Vencimento;Cliente;Nome da Receita;Valor Original\n'
            '14/10/2026;Ana;OS 1;100\n', entity='receber')
        mapping = json.loads(migration.mapping_json)
        self.assertEqual(mapping['vencimento'], 0)
        self.assertEqual(mapping['contraparte'], 1)
        self.assertEqual(mapping['descricao'], 2)
        self.assertEqual(mapping['valor'], 3)
        self.assertNotIn('origem_id', mapping)

    def test_report_uses_imported_name_and_totals_without_items(self):
        migration = self.prepare('OS;Cliente;Data da OS;Valor Serviços;Valor Produtos;Valor Total\n'
            '99;ANA GOL ABC1234;14/09/2026;70;220;280\n', entity='ordens_servico')
        self.confirm(migration)
        self.drain()
        page = self.browser.get('/relatorios?start_date=2026-09-01&end_date=2026-09-30&status=TODOS').get_data(as_text=True)
        self.assertIn('CLIENTE <strong>ANA</strong>', page)
        self.assertNotIn('CLIENTE <strong>Cliente VHSys (Importado)</strong>', page)
        self.assertIn('280,00', page)
        self.assertIn('220,00', page)
        self.assertIn('70,00', page)
        self.assertIn('O detalhamento dos itens não foi informado', page)
        self.assertEqual(len(WorkOrder.query.one().items), 0)

    def test_receivables_recover_single_and_split_payments_idempotently(self):
        from app.data_migration.payments import reconcile_os_payments
        db.session.add_all([PaymentMethod(nome='PIX', tipo='PIX'), PaymentMethod(nome='Dinheiro', tipo='DINHEIRO')])
        migration = self.prepare('OS;Cliente;Data da OS;Valor Total\n'
            '11;Ana GOL ABC1234;14/09/2026;100\n12;Ana GOL ABC1234;14/09/2026;100\n', entity='ordens_servico')
        self.confirm(migration)
        self.drain()
        path = Path(self.tmp.name) / 'receber.csv'
        path.write_text('Nome da Receita;Forma de Pagamento;Valor Original\n'
            'Ordem de Serviço 11;PIX;100\nOrdem de Serviço 12;PIX;40\nOrdem de Serviço 12;Dinheiro;60\n', encoding='utf-8')
        self.assertEqual([r['status'] for r in reconcile_os_payments(path)], ['PRONTA', 'PRONTA'])
        self.assertTrue(all(o.payment_method_id is None and not o.payments for o in WorkOrder.query.all()))
        self.assertEqual([r['status'] for r in reconcile_os_payments(path, apply=True)], ['ATUALIZADA', 'ATUALIZADA'])
        db.session.commit()
        self.assertEqual([r['status'] for r in reconcile_os_payments(path, apply=True)], ['JA_PREENCHIDA', 'JA_PREENCHIDA'])
        order = WorkOrder.query.filter_by(numero='12').one()
        self.assertEqual(len(order.payments), 2)
        self.assertEqual(sum(p.valor for p in order.payments), Decimal('100'))

    def test_receivables_mismatch_does_not_update_order(self):
        from app.data_migration.payments import reconcile_os_payments
        db.session.add(PaymentMethod(nome='PIX', tipo='PIX'))
        migration = self.prepare('OS;Cliente;Data da OS;Valor Total\n'
            '13;Ana GOL ABC1234;14/09/2026;100\n', entity='ordens_servico')
        self.confirm(migration)
        self.drain()
        path = Path(self.tmp.name) / 'receber.csv'
        path.write_text('Nome da Receita;Forma de Pagamento;Valor Original\n'
            'Ordem de Serviço 13;PIX;90\n', encoding='utf-8')
        self.assertEqual(reconcile_os_payments(path, apply=True)[0]['status'], 'PENDENCIA')
        self.assertIsNone(WorkOrder.query.one().payment_method_id)

    def test_automatic_plate_vehicle_payment_preview_matches_import(self):
        client = Client(nome='Maria da Silva')
        method = PaymentMethod(nome='Cartão de crédito', tipo='CREDITO')
        db.session.add_all([client, method])
        db.session.commit()
        migration = self.prepare('OS;Cliente;Data da OS;Forma de Pagamento\n'
            'AUTO-1;Maria da Silva ASTRA ABC 1D23;14/09/2026;cartao de credito\n', entity='ordens_servico')
        page = self.browser.get(f'/configuracoes/migracao/{migration.id}').get_data(as_text=True)
        self.assertIn('ABC1D23', page)
        self.assertIn('Informações separadas automaticamente', page)
        self.assertIn('<td>ASTRA</td>', page)
        self.assertEqual(db.session.query(WorkOrder).count(), 0)
        self.confirm(migration)
        self.drain()
        order = db.session.scalar(select(WorkOrder).where(WorkOrder.numero == 'AUTO-1'))
        self.assertEqual((order.client_nome, order.veiculo_descricao, order.placa), ('Maria da Silva', 'ASTRA', 'ABC1D23'))
        self.assertEqual(order.payment_method_id, method.id)

    def test_explicit_payment_in_notes_and_missing_payment(self):
        db.session.add_all([Client(nome='Ana'), PaymentMethod(nome='PIX', tipo='PIX')])
        db.session.commit()
        migration = self.prepare('OS;Cliente;Data da OS;Observações\n'
            'AUTO-2;Ana GOL ABC-1234;14/09/2026;Pagamento: PIX\n'
            'AUTO-3;Ana GOL ABC-1234;14/09/2026;Sem observação\n'
            'AUTO-4;Ana GOL ABC-1234;14/09/2026;Pagamento: desconhecido\n', entity='ordens_servico')
        self.confirm(migration)
        self.drain()
        self.assertEqual((migration.imported, migration.errors), (2, 1))
        orders = list(db.session.scalars(select(WorkOrder).order_by(WorkOrder.numero)))
        self.assertIsNotNone(orders[0].payment_method_id)
        self.assertIsNone(orders[1].payment_method_id)

    def test_conflicting_plates_are_rejected(self):
        migration = self.prepare('OS;Cliente;Placa;Data da OS\n'
            'AUTO-5;Ana GOL ABC-1234;DEF5678;14/09/2026\n', entity='ordens_servico')
        self.confirm(migration)
        self.drain()
        self.assertEqual(migration.errors, 1)
        self.assertEqual(db.session.query(WorkOrder).count(), 0)

    def test_upload_wakes_worker_and_exposes_pending_queue(self):
        with patch('app.data_migration.routes.start_worker') as start:
            migration = self.upload('nome;cpf_cnpj\nTeste;12345678901')
            start.assert_called_once_with(self.app)
        status = self.browser.get(f'/configuracoes/migracao/{migration.id}/status').json
        self.assertEqual(status['queue_status'], 'PENDENTE')
        self.assertEqual(db.session.query(Client).count(), 0)

    def test_xls_html_fragment_with_bom_and_utf16(self):
        html = '<table><tr><th>nome</th></tr><tr><td>João</td></tr></table>'
        for encoding in ('utf-8-sig', 'utf-16'):
            migration = self.prepare(html.encode(encoding), filename='outro-sistema.xls')
            self.assertEqual(migration.total, 1)

    def test_background_worker_restarts_after_idle(self):
        from app.data_migration.worker import MigrationWorker
        from app.jobs import enqueue
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({'TESTING': True, 'APP_ENV': 'testing', 'AUTO_CREATE_SCHEMA': True,
                'SECRET_KEY': 'worker-test', 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(directory) / 'worker.db'),
                'SQLALCHEMY_ENGINE_OPTIONS': {}, 'MIGRATION_STORAGE': directory})
            worker = MigrationWorker(app)
            for _ in range(2):
                with app.app_context():
                    user = db.session.scalar(select(User))
                    if not user:
                        user = User(username='worker', nome='Worker', role='ADMINISTRADOR')
                        user.set_password('test')
                        db.session.add(user)
                        db.session.flush()
                    Path(directory, 'sample.csv').write_text('nome\nTeste\n', encoding='utf-8')
                    migration = DataMigration(user_id=user.id, entity='clientes', source='Teste',
                        filename='sample.csv', storage_name='sample.csv', options_json=json.dumps(
                            dict(encoding='utf-8-sig', delimiter='auto', table=0, header_row=1)))
                    db.session.add(migration)
                    db.session.flush()
                    migration_id = migration.id
                    enqueue('MIGRATION_PREPARE', {'migration_id': migration_id})
                    db.session.commit()
                worker.start()
                thread = worker.thread
                if thread:
                    thread.join(timeout=10)
                    self.assertFalse(thread.is_alive())
                with app.app_context():
                    self.assertEqual(db.session.get(DataMigration, migration_id).status, 'PREVIA')
                    self.assertEqual(db.session.query(Client).count(), 0)
            with app.app_context():
                db.session.remove()
                db.engine.dispose()

    def test_csv_preview_confirmation_validation_and_deduplication(self):
        existing = Client(nome='Já cadastrado', cpf_cnpj='123.456.789-01')
        db.session.add(existing)
        db.session.commit()
        migration = self.prepare('nome;cpf_cnpj;email\nExistente;12345678901;a@b.com\nJoão;12345678902;j@b.com\nJoão;12345678902;j@b.com\n;12345678903;ruim\n')
        self.assertEqual(Client.query.count(), 1)
        self.assertEqual(migration.total, 4)
        page = self.browser.get(f'/configuracoes/migracao/{migration.id}')
        self.assertEqual(page.status_code, 200)
        self.assertIn('João'.encode(), page.data)
        self.confirm(migration)
        self.drain()
        self.assertEqual((migration.imported, migration.skipped, migration.errors), (1, 2, 1))
        self.assertEqual(existing.nome, 'Já cadastrado')
        self.assertEqual(Client.query.count(), 2)
        self.assertEqual(self.post(f'/configuracoes/migracao/{migration.id}', {'action': 'import'}).status_code, 409)
        report = self.browser.get(f'/configuracoes/migracao/{migration.id}/relatorio.csv')
        self.assertEqual(report.status_code, 200)
        self.assertIn(b'IGNORADO', report.data)
        self.assertIn(b'ERRO', report.data)
        self.assertIn('campo obrigatório'.encode(), report.data)

    def test_bulk_is_batched_and_redelivery_does_not_duplicate(self):
        migration = self.prepare('codigo;nome;preco_venda\n' + ''.join(f'P{i};Peça {i};12,50\n' for i in range(1201)), entity='produtos')
        self.confirm(migration)
        queries = []
        def count(_conn, _cursor, statement, _parameters, _context, _many):
            queries.append(statement)
        event.listen(db.engine, 'before_cursor_execute', count)
        try:
            self.drain()
        finally:
            event.remove(db.engine, 'before_cursor_execute', count)
        self.assertEqual(migration.imported, 1201)
        self.assertLess(len(queries), 200, f'{len(queries)} queries for 1201 rows')
        import_batch(migration.id)
        db.session.commit()
        self.assertEqual(Product.query.count(), 1201)
        repeated = self.prepare('codigo;nome\nP1;Não substituir\n', entity='produtos')
        self.confirm(repeated)
        self.drain()
        self.assertEqual(repeated.skipped, 1)

    def test_xlsx_read_only_dates_and_financial_idempotency(self):
        workbook = Workbook()
        workbook.active.append(['ignorar'])
        sheet = workbook.create_sheet('Contas')
        sheet.append(['Relatório'])
        sheet.append(['origem_id', 'descricao', 'valor', 'vencimento'])
        sheet.append(['R001', 'Parcela', 1234.56, date(2026, 10, 12)])
        buffer = io.BytesIO()
        workbook.save(buffer)
        migration = self.prepare(buffer.getvalue(), 'contas.xlsx', 'receber', table='2', header_row='2')
        self.confirm(migration)
        self.drain()
        entry = FinancialEntry.query.one()
        self.assertEqual(entry.valor, Decimal('1234.56'))
        self.assertEqual(entry.vencimento, date(2026, 10, 12))
        self.assertEqual(entry.status, 'PENDENTE')
        self.assertIsNone(entry.bank_account_id)
        repeated = self.prepare('origem_id;descricao;valor;vencimento\nR001;Outro nome;50;12/10/2026\n', entity='receber')
        self.confirm(repeated)
        self.drain()
        self.assertEqual(repeated.skipped, 1)
        self.assertEqual(FinancialEntry.query.count(), 1)

    def test_html_tables_encoding_and_no_script_execution(self):
        html = '<table><tr><td>Outro</td></tr></table><table><tr><th>nome</th><th>telefone</th></tr><tr><td>João &amp; Filhos<script>alert(1)</script></td><td>11999999999</td></tr></table>'
        migration = self.prepare(html.encode('cp1252'), 'relatorio.html', table='2', encoding='cp1252')
        self.confirm(migration)
        self.drain()
        self.assertEqual(Client.query.one().nome, 'João & Filhos')

    def test_stock_balance_has_auditable_initial_movement(self):
        migration = self.prepare('codigo;nome;estoque_atual;custo\nF1;Filtro;20;8,50\n', entity='produtos')
        self.confirm(migration)
        self.drain()
        movement = InventoryMovement.query.one()
        self.assertEqual(movement.quantity, 20)
        self.assertEqual(movement.balance_after, Product.query.one().estoque_atual)
        self.assertEqual(movement.user_id, self.admin.id)

    def test_vehicle_relationship_and_missing_client(self):
        db.session.add(Client(nome='Dono', cpf_cnpj='123.456.789-01'))
        db.session.commit()
        migration = self.prepare('cliente_documento;placa;descricao\n12345678901;ABC-1234;Carro\n12345678902;DEF1A23;Outro\n', entity='veiculos')
        self.confirm(migration)
        self.drain()
        self.assertEqual(migration.imported, 1)
        self.assertEqual(migration.errors, 1)
        vehicle = Vehicle.query.one()
        self.assertEqual(vehicle.client.nome, 'Dono')
        self.assertEqual(vehicle.placa, 'ABC1234')

    def test_suppliers_services_and_tsv(self):
        migration = self.prepare('nome\tcnpj_cpf\nFornecedor\t12345678000199\n', 'dados.tsv', 'fornecedores')
        self.confirm(migration)
        self.drain()
        self.assertEqual(Supplier.query.one().cnpj_cpf, '12345678000199')
        services = self.prepare('nome;preco_base\nAlinhamento;80,00\n', entity='servicos')
        self.confirm(services)
        self.drain()
        self.assertEqual(Service.query.one().preco_base, Decimal('80'))

    def test_multiple_uploads_and_invalid_extension_are_atomic(self):
        response = self.post('/configuracoes/migracao/enviar', {'source': 'Legado', 'entity': 'clientes',
            'files': [(io.BytesIO(b'nome\nA\n'), 'a.csv'), (io.BytesIO(b'nome\nB\n'), 'b.csv')]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DataMigration.query.count(), 2)
        self.assertEqual(AsyncJob.query.count(), 2)
        self.post('/configuracoes/migracao/enviar', {'source': 'Legado', 'entity': 'clientes',
            'files': [(io.BytesIO(b'nome\nC\n'), 'c.csv'), (io.BytesIO(b'bad'), 'x.exe')]})
        self.assertEqual(DataMigration.query.count(), 2)

    def test_required_mapping_duplicate_mapping_and_confirmation(self):
        migration = self.prepare('NOME CUSTOM;CONTATO\nTeste;abc@exemplo.com\n')
        url = f'/configuracoes/migracao/{migration.id}'
        for fields in ({'email': '1'}, {'nome': '0', 'email': '0'}, {'nome': '-1'}, {'nome': '200'}, {'nome': 'zero'}):
            response = self.post(url, {**fields, 'action': 'import', 'confirmed': 'yes'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(migration.status, 'PREVIA')
        self.post(url, {'nome': '0', 'email': '1', 'action': 'import'})
        self.assertEqual(migration.status, 'PREVIA')
        self.assertEqual(Client.query.count(), 0)

    def test_access_control_csrf_and_escaping(self):
        migration = self.prepare('nome\n<img src=x onerror=alert(1)>\n')
        page = self.browser.get(f'/configuracoes/migracao/{migration.id}')
        self.assertNotIn(b'<img src=x', page.data)
        self.assertIn(b'&lt;img', page.data)
        self.assertEqual(self.browser.post('/configuracoes/migracao/enviar').status_code, 400)
        self.admin.role = 'RECEPCIONISTA'
        db.session.commit()
        for path in ('', f'/{migration.id}', f'/{migration.id}/status', f'/{migration.id}/relatorio.csv', '/modelo/clientes.csv'):
            self.assertEqual(self.browser.get('/configuracoes/migracao' + path).status_code, 403)
        self.assertEqual(self.post('/configuracoes/migracao/enviar', {}).status_code, 403)

    def test_report_neutralizes_spreadsheet_formulas(self):
        migration = self.prepare('nome\n=HYPERLINK("x")\n')
        report = self.browser.get(f'/configuracoes/migracao/{migration.id}/relatorio.csv').data.decode('utf-8-sig')
        self.assertIn("'=HYPERLINK", report)

    def test_bad_file_has_readable_failure_without_business_writes(self):
        migration = self.upload('sem registros\n')
        job = run_next_job()
        self.assertEqual(job.status, 'FALHOU')
        self.assertEqual(migration.status, 'ERRO_LEITURA')
        self.assertIn('não contém', migration.last_error)
        self.assertEqual(Client.query.count(), 0)

    def test_transaction_failure_rolls_back_and_can_resume(self):
        migration = self.prepare('nome\nTeste\n')
        self.confirm(migration)
        job = AsyncJob.query.filter_by(job_type='MIGRATION_IMPORT').one()
        job.attempts = 4
        db.session.commit()
        with patch('app.data_migration.service.write_group', side_effect=OperationalError('test', {}, Exception('DB down'))):
            result = run_next_job()
        self.assertEqual(result.status, 'FALHOU')
        self.assertEqual(migration.status, 'ERRO_IMPORTACAO')
        self.assertEqual(Client.query.count(), 0)
        self.assertEqual(MigrationKey.query.count(), 0)
        self.assertEqual(migration.processed, 0)
        self.assertEqual(self.post(f'/configuracoes/migracao/{migration.id}/retomar', {}).status_code, 302)
        self.drain()
        self.assertEqual(migration.imported, 1)

    def test_strict_amount_and_row_shape_validation(self):
        for value in ('NaN', 'Infinity', '-1', '1.234', '10000000000'):
            with self.assertRaises(ValueError):
                parse_decimal(value)
        self.assertEqual(parse_decimal('R$ 1.234,56'), Decimal('1234.56'))
        migration = self.prepare('nome\nTeste\n')
        with self.assertRaises(ValueError):
            convert(migration, ['Teste', 'Extra'], {'nome': 0})

    def test_reader_bounds_and_nonfirst_header(self):
        path = Path(self.tmp.name) / 'rows.csv'
        path.write_text('Título\nnome;email\nTeste;t@b.com\n', encoding='utf-8')
        options = {'encoding': 'utf-8-sig', 'delimiter': ';', 'table': 1, 'header_row': 2}
        self.assertEqual(list(read_table(path, options)), [(0, ['nome', 'email']), (3, ['Teste', 't@b.com'])])
        path.write_text('nome\n' + 'a' * 16001, encoding='utf-8')
        options['header_row'] = 1
        with self.assertRaises(ValueError):
            list(read_table(path, options))

    def test_status_index_templates_and_private_headers(self):
        migration = self.prepare('nome\nTeste\n')
        for path in ('', f'/{migration.id}', f'/{migration.id}/status', '/modelo/clientes.csv'):
            response = self.browser.get('/configuracoes/migracao' + path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.browser.get('/configuracoes/migracao/999/status').status_code, 404)

    def test_committed_batch_survives_later_failure_and_retry(self):
        migration = self.prepare('nome\n' + ''.join(f'Cliente {i}\n' for i in range(501)))
        self.confirm(migration)
        self.assertEqual(run_next_job().status, 'CONCLUIDA')
        self.assertEqual(migration.imported, 500)
        pending = AsyncJob.query.filter_by(job_type='MIGRATION_IMPORT', status='PENDENTE').one()
        pending.attempts = 4
        db.session.commit()
        with patch('app.data_migration.service.write_group', side_effect=OperationalError('test', {}, Exception('DB down'))):
            self.assertEqual(run_next_job().status, 'FALHOU')
        self.assertEqual(Client.query.count(), 500)
        self.assertEqual(migration.imported, 500)
        self.assertEqual(self.post(f'/configuracoes/migracao/{migration.id}/retomar', {}).status_code, 302)
        self.drain()
        self.assertEqual(Client.query.count(), 501)
        self.assertEqual(migration.imported, 501)
        self.assertEqual(MigrationRow.query.filter_by(result='IMPORTADO').count(), 501)

    def test_bad_xlsx_and_encoding_fail_without_repeated_retries(self):
        for content, filename in ((b'not a zip', 'bad.xlsx'), ('nome\nJoão\n'.encode('cp1252'), 'bad.csv')):
            migration = self.upload(content, filename)
            job = run_next_job()
            self.assertEqual(job.status, 'FALHOU')
            self.assertEqual(job.attempts, 1)
            self.assertEqual(migration.status, 'ERRO_LEITURA')

    def test_worker_watch_once_does_not_wait(self):
        with patch('app.jobs.time.sleep') as sleep:
            result = self.app.test_cli_runner().invoke(args=['jobs-worker', '--watch', '--once'])
        self.assertEqual(result.exit_code, 0, result.output)
        sleep.assert_not_called()

    def test_server_upload_limit_is_enforced(self):
        self.app.config['MIGRATION_MAX_UPLOAD_BYTES'] = 1024
        response = self.post('/configuracoes/migracao/enviar', {'source': 'Legado', 'entity': 'clientes',
            'files': (io.BytesIO(b'x' * 2048), 'big.csv')})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(DataMigration.query.count(), 0)

    def test_schema_upgrade_downgrade_and_upgrade(self):
        from flask_migrate import stamp, upgrade, downgrade
        for model in (MigrationKey, MigrationRow, DataMigration):
            model.__table__.drop(db.engine)
        stamp(revision='20260909_09')
        upgrade(revision='20260914_10')
        for model in (DataMigration, MigrationRow, MigrationKey):
            columns = {column['name'] for column in inspect(db.engine).get_columns(model.__tablename__)}
            self.assertEqual(columns, set(model.__table__.columns.keys()))
        downgrade(revision='20260909_09')
        self.assertNotIn('data_migrations', inspect(db.engine).get_table_names())
        upgrade(revision='20260914_10')
        self.assertIn('data_migrations', inspect(db.engine).get_table_names())

    def test_preview_precedes_confirmation_and_shows_original_values(self):
        migration = self.prepare('codigo;nome;preco_venda\n' + ''.join(f'X{i};Produto {i};12,50\n' for i in range(25)), entity='produtos')
        page = self.browser.get(f'/configuracoes/migracao/{migration.id}').get_data(as_text=True)
        self.assertLess(page.index('Prévia do que será importado'), page.index('id="migration-confirmation"'))
        self.assertIn('No arquivo: 12,50', page)
        self.assertIn('12.50', page)
        self.assertIn('Produto 19', page)
        self.assertNotIn('Produto 20', page)
        self.assertEqual(Product.query.count(), 0)

    def test_changed_mapping_requires_preview_before_import(self):
        migration = self.prepare('nome;alternativo\nNome original;Nome correto\n')
        url = f'/configuracoes/migracao/{migration.id}'
        response = self.post(url, {'nome': '1', 'action': 'import', 'confirmed': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(migration.status, 'PREVIA')
        self.assertEqual(Client.query.count(), 0)
        self.assertEqual(AsyncJob.query.filter_by(job_type='MIGRATION_IMPORT').count(), 0)
        self.assertIn(b'Nome correto', self.browser.get(url).data)
        self.confirm(migration)
        self.drain()
        self.assertEqual(Client.query.one().nome, 'Nome correto')

    def test_work_order_from_nested_html_disguised_as_xls(self):
        client = Client(nome='MARILZA', cpf_cnpj='12345678901')
        employee = Employee(nome='GABRIEL', funcao='MECÂNICO')
        db.session.add_all([client, employee])
        db.session.flush()
        vehicle = Vehicle(client_id=client.id, placa='DSN4667', descricao='ASTRA')
        db.session.add(vehicle)
        db.session.commit()
        html = '''<html><body><table><tr><td>Relatório</td></tr><tr><td>
          <table><tr><th>OS</th><th>Cliente</th><th>Vendedor</th><th>Valor Serviços</th>
          <th>Valor Produtos</th><th>Valor Total</th><th>Total de parcelas</th>
          <th>Data da OS</th><th>Situação</th><th>Observações</th></tr>
          <tr><td>8702</td><td>MARILZA ASTRA DSN-4667</td><td>GABRIEL</td><td>R$ 70,00</td>
          <td>R$ 220,00</td><td>R$ 290,00</td><td>1</td><td>08/09/2026</td>
          <td>Atendido</td><td>Revisão concluída</td></tr></table></td></tr></table></body></html>'''
        migration = self.prepare(html, 'ordens.xls', 'ordens_servico')
        mapping = json.loads(migration.mapping_json)
        self.assertEqual(mapping['numero'], 0)
        self.assertEqual(mapping['cliente_veiculo'], 1)
        page = self.browser.get(f'/configuracoes/migracao/{migration.id}').get_data(as_text=True)
        self.assertIn('Prévia do que será importado', page)
        self.assertIn('MARILZA ASTRA DSN-4667', page)
        self.assertIn('FINALIZADA', page)
        self.confirm(migration)
        self.drain()
        order = WorkOrder.query.one()
        self.assertEqual(order.numero, '8702')
        self.assertEqual(order.client_id, client.id)
        self.assertEqual(order.vehicle_id, vehicle.id)
        self.assertEqual(order.employee_id, employee.id)
        self.assertEqual(order.placa, 'DSN4667')
        self.assertEqual(order.veiculo_descricao, 'ASTRA')
        self.assertEqual(order.status, 'FINALIZADA')
        self.assertEqual(order.current_stage, 'PRONTO')
        self.assertEqual(order.total_servicos, Decimal('70'))
        self.assertEqual(order.total_pecas, Decimal('220'))
        self.assertEqual(order.total_geral, Decimal('290'))
        self.assertIn('Responsável na origem: GABRIEL', order.observacoes)
        self.assertEqual(WorkOrderStatusHistory.query.one().status, 'FINALIZADA')

        repeated = self.prepare(html, 'ordens-repetidas.html', 'ordens_servico')
        self.confirm(repeated)
        self.drain()
        self.assertEqual(repeated.skipped, 1)
        self.assertEqual(WorkOrder.query.count(), 1)

    def test_work_order_without_existing_client_uses_legacy_fallback(self):
        migration = self.prepare('OS;Cliente;Data da OS\n10;CLIENTE DESCONHECIDO GOL ABC1234;01/09/2026\n',
                                 entity='ordens_servico')
        self.confirm(migration)
        self.drain()
        self.assertEqual(migration.errors, 0)
        order = WorkOrder.query.one()
        self.assertEqual(order.client.nome, 'Cliente VHSys (Importado)')
        self.assertEqual(order.client_nome, 'CLIENTE')
        self.assertEqual(order.veiculo_descricao, 'DESCONHECIDO GOL')
        self.assertEqual(order.placa, 'ABC1234')

    def test_completed_migration_can_retry_only_error_rows(self):
        db.session.add(Client(nome='Ana'))
        db.session.commit()
        migration = self.prepare('OS;Cliente;Data da OS;Forma de Pagamento\n'
            '20;Ana GOL ABC1234;01/09/2026;PIX\n', entity='ordens_servico')
        self.confirm(migration)
        self.drain()
        self.assertEqual((migration.status, migration.errors), ('CONCLUIDA', 1))
        db.session.add(PaymentMethod(nome='PIX', tipo='PIX'))
        db.session.commit()
        response = self.post(f'/configuracoes/migracao/{migration.id}/retomar-erros', {})
        self.assertEqual(response.status_code, 302)
        self.drain()
        self.assertEqual((migration.imported, migration.errors, migration.total), (1, 0, 1))
        self.assertEqual(WorkOrder.query.one().payment_method.nome, 'PIX')


if __name__ == '__main__':
    unittest.main()
