import importlib.util
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('reload_vhsys', Path(__file__).resolve().parents[1] / 'scripts' / 'reload_vhsys.py')
reload_vhsys = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reload_vhsys)


def grid(columns, rows, subs=None):
    head = ''.join(f'<th data-field="{f}">{label}</th>' for f, label in columns)
    body = ''
    for i, row in enumerate(rows, 1):
        body += f'<tr class="table-row-body" data-id="{i}">' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>'
        if subs and subs.get(i):
            fields, items = subs[i]
            sub_head = ''.join(f'<th data-field="{f}">{f}</th>' for f in fields)
            sub_body = ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in item) + '</tr>' for item in items)
            body += (f'<tr class="Table_L1" data-id="{i}"><td><table data-subtable="true" data-parent="{i}">'
                     f'<thead><tr>{sub_head}</tr></thead><tbody>{sub_body}</tbody></table></td></tr>')
    return f'<html><body><table id="tblGrid"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></body></html>'


PEOPLE = [(f, f) for f in ('Nome', 'Fantasia', 'CNPJCPF', 'IE', 'RG', 'Telefone', 'Email', 'Endereco', 'Numero', 'Bairro',
                           'Complemento', 'CEP', 'Cidade', 'Estado', 'Contato', 'DataNascimento', 'Observacao', 'DataCad', 'Celular')]
OS_COLS = [(f, f) for f in ('Ordem', 'Cliente', 'Vendedor', 'Profissional', 'ValorServicos', 'ValorProdutos', 'ValorTotal',
                            'TotalParcelas', 'DataPedido', 'DataEntrega', 'DataRealizacao', 'NFSeEmitida', 'Estoque',
                            'Situacao', 'DataCad', 'DataMod', 'Observacoes')]
RECEBER = [('Vencimento', 'Vencimento'), ('NomeConta', 'Nome da Receita'), ('FormaPag', 'Forma de Pagamento'),
           ('Banco', 'Conta Bancária'), ('Situacao', 'Situação'), ('ValorOriginal', 'Valor Original'),
           ('ValorBaixado', 'Valor Baixado'), ('ValorPago', 'Valor Recebido')]
EXTRATO = [(f, f) for f in ('Data', 'Lancamento', 'FormaPag')]


class ReloadVhsysTest(unittest.TestCase):
    def test_build_fills_payment_from_extrato_and_splits_plate(self):
        files = {
            'ClientesApenas.html': grid(PEOPLE, [['ANA GOL ABC-1234'] + [''] * 15 + ['', '01/01/2024', '11999']]),
            'Clientes.html': grid(PEOPLE, [['AUTOPECAS LTDA', '', '12.345.678/0001-90'] + [''] * 16]),
            'ServicosMaisVendidos.html': grid([('Servico', 'S'), ('ValorServ', 'V')], [['ALINHAMENTO', 'R$ 60,00']]),
            'EntradasMercadoria.html': grid([(f, f) for f in ('Entrada', 'NFCompra', 'Fornecedor', 'CNPJ', 'Telefone', 'Email',
                'ValorFrete', 'ValorTotal', 'ValorDesconto', 'Transportadora', 'DataPedido', 'DataEmissao', 'Chave', 'Obs', 'DataCad')],
                [['1', '99', 'AUTOPECAS LTDA', '12345678000190', '', '', 'R$ 0,00', 'R$ 20,00', 'R$ 0,00', '', '02/01/2024',
                  '01/01/2024', '', '', '02/01/2024']],
                {1: (['Produto', 'Codigo', 'Unidade', 'Qtde', 'ValorUnit', 'CFOP', 'NCM', 'ValorTotal', 'EstoqueAtual'],
                     [['FILTRO', 'F1', 'UN', '2', 'R$ 10,00', '5405', '8421', 'R$ 20,00', '3']])}),
            'OrdemServico.html': grid(OS_COLS, [
                ['10', 'ANA GOL ABC-1234', 'DIEGO', 'ANDRE', 'R$ 60,00', 'R$ 40,00', 'R$ 100,00', '1', '03/01/2024',
                 '03/01/2024', '', 'NÃO', 'SIM', 'Atendido', '03/01/2024', '', ''],
                ['11', 'BRUNO UNO XYZ-9A87', 'DIEGO', '', 'R$ 50,00', 'R$ 0,00', 'R$ 50,00', '1', '04/01/2024',
                 '', '', 'NÃO', 'NÃO', 'Em aberto', '04/01/2024', '', '']],
                {1: (['Produto', 'Tipo', 'Qtde', 'ValorUnit', 'ValorTotal', 'ItemRejeitado'],
                     [['ALINHAMENTO', 'Serviço', '1', 'R$ 60,00', 'R$ 60,00', 'Não'],
                      ['FILTRO', 'Produto', '1', 'R$ 40,00', 'R$ 40,00', 'Não']])}),
            'ContasReceber.html': grid(RECEBER, [
                ['03/01/2024', 'Ordem de Serviço 10', '', 'JURIDICA', 'Recebido (03/01/2024)', 'R$ 100,00', 'R$ 100,00', 'R$ 100,00'],
                ['04/01/2024', 'Ordem de Serviço 11', 'Cartão de Crédito', 'POUPANÇA', 'Em aberto', 'R$ 50,00', 'R$ 0,00', 'R$ 0,00']]),
            'ContasPagar.html': grid([(f, label.replace('Receita', 'Despesa').replace('Recebido', 'Pago')) for f, label in RECEBER], [
                ['05/01/2024', 'ALUGUEL', 'Boleto', 'Dinheiro', 'Pago (05/01/2024)', 'R$ 30,00', 'R$ 30,00', 'R$ 30,00']]),
            'Extrato24-25.html': grid(EXTRATO, [['03/01/2024', 'Ordem de Serviço 10', 'PIX']]),
            'Extrato25-26.html': grid(EXTRATO, []),
            'NotasFiscaisServico.html': grid([(f, f) for f in ('RPS', 'Nota', 'Chave', 'Situacao', 'DataEmissao', 'DataPedido', 'DataMod')],
                                             [['1', '7', 'K', 'Cancelado', '', '03/01/2024', '']]),
        }
        with tempfile.TemporaryDirectory() as folder:
            for name, content in files.items():
                (Path(folder) / name).write_text(content, encoding='utf-8')
            rows, report = reload_vhsys.build(Path(folder))
        methods = {m['id']: m['nome'] for m in rows['payment_methods']}
        orders = {o['numero']: o for o in rows['work_orders']}
        self.assertEqual(methods[orders['10']['payment_method_id']], 'Pix')
        self.assertEqual(methods[orders['11']['payment_method_id']], 'Cartão de Crédito')
        self.assertEqual((orders['10']['placa'], orders['10']['veiculo_descricao'], orders['10']['status']), ('ABC1234', 'ANA GOL', 'FINALIZADA'))
        self.assertEqual(orders['10']['client_id'], 1)  # matched the registered client
        self.assertEqual(len(rows['clients']), 2)
        self.assertEqual({b['nome']: b['saldo_atual'] for b in rows['bank_accounts']},
                         {'JURIDICA': Decimal('12679.76'), 'Dinheiro': Decimal('16213.92')})
        entries = {e['descricao']: e for e in rows['financial_entries']}
        self.assertEqual(entries['ANA GOL ABC-1234']['reference_type'], 'OS')
        self.assertIsNone(entries['BRUNO UNO XYZ-9A87']['bank_account_id'])  # POUPANÇA is ignored
        self.assertEqual(rows['stock_entries'][0]['supplier_id'], 1)
        self.assertEqual(rows['products'][0]['estoque_atual'], Decimal('3.00'))
        self.assertEqual(rows['fiscal_documents'][0]['status'], 'CANCELADO')
        self.assertEqual(report['orders_without_payment'], [])


if __name__ == '__main__':
    unittest.main()
