from __future__ import annotations

from decimal import Decimal

from .models import BankAccount, Budget, BudgetItem, Client, Employee, PaymentMethod, Product, Service, User, db
from .services import recalculate_budget_totals


def seed_database() -> None:
    if User.query.first():
        return

    admin = User(username='admin', role='ADMINISTRADOR', nome='Administrador')
    admin.set_password('admin123')
    mechanic_user = User(username='mecanico', role='MECANICO', nome='Mecânico Demo')
    mechanic_user.set_password('mecanico123')
    db.session.add_all([admin, mechanic_user])

    employees = [
        Employee(nome='Administrador', funcao='Gerente', telefone='11999990000', email='admin@autocenter.local'),
        Employee(nome='Mecânico Demo', funcao='Mecânico', telefone='11999991111', email='mecanico@autocenter.local'),
    ]
    db.session.add_all(employees)

    bank_accounts = [
        BankAccount(nome='Conta Principal', banco='Banco do Brasil', agencia='1234-5', conta='98765-4', saldo_inicial=Decimal('5000.00'), saldo_atual=Decimal('5000.00')),
        BankAccount(nome='Caixa PIX', banco='Inter', agencia='0001', conta='112233-0', saldo_inicial=Decimal('1500.00'), saldo_atual=Decimal('1500.00')),
    ]
    db.session.add_all(bank_accounts)

    payment_methods = [
        PaymentMethod(nome='Dinheiro', tipo='DINHEIRO', permite_parcelamento=False, parcelas_maximas=1),
        PaymentMethod(nome='Pix', tipo='PIX', permite_parcelamento=False, parcelas_maximas=1),
        PaymentMethod(nome='Cartão de Débito', tipo='DEBITO', permite_parcelamento=False, parcelas_maximas=1),
        PaymentMethod(nome='Cartão de Crédito', tipo='CREDITO', permite_parcelamento=True, parcelas_maximas=12),
    ]
    db.session.add_all(payment_methods)

    client = Client(
        nome='Cliente Exemplo',
        cpf_cnpj='12345678900',
        telefone='11988887777',
        email='cliente@example.com',
        endereco='Rua das Oficinas, 100 - Centro - São Paulo/SP',
        observacoes='Cliente criado automaticamente para demonstração.',
    )
    db.session.add(client)
    db.session.flush()

    services = [
        Service(nome='Troca de óleo', descricao='Troca de óleo e filtro', preco_base=Decimal('80.00')),
        Service(nome='Alinhamento', descricao='Alinhamento computadorizado', preco_base=Decimal('120.00')),
        Service(nome='Balanceamento', descricao='Balanceamento das rodas', preco_base=Decimal('60.00')),
    ]
    db.session.add_all(services)
    db.session.flush()

    parts = [
        Product(codigo='PEC-001', nome='Óleo 5W30', categoria='Lubrificantes', marca='Shell', unidade='LT', custo=Decimal('30.00'), preco_venda=Decimal('45.00')),
        Product(codigo='PEC-002', nome='Filtro de óleo', categoria='Filtros', marca='Bosch', unidade='UN', custo=Decimal('18.00'), preco_venda=Decimal('29.90')),
        Product(codigo='PEC-003', nome='Pastilha de freio', categoria='Freios', marca='Cobreq', unidade='JG', custo=Decimal('90.00'), preco_venda=Decimal('149.90')),
    ]
    db.session.add_all(parts)
    db.session.flush()

    budget = Budget(
        client_id=client.id,
        numero='ORC-00001',
        status='ABERTO',
        placa='ABC1D23',
        veiculo_descricao='Volkswagen Gol 1.6 2019',
        observacoes='Orçamento de exemplo gerado na carga inicial.',
        desconto=Decimal('0'),
    )
    db.session.add(budget)
    db.session.flush()

    budget_items = [
        BudgetItem(budget_id=budget.id, item_type='SERVICO', reference_id=services[0].id, descricao=services[0].nome, quantidade=Decimal('1'), valor_unitario=services[0].preco_base, desconto=Decimal('0'), total=services[0].preco_base),
        BudgetItem(budget_id=budget.id, item_type='PECA', reference_id=parts[0].id, descricao=parts[0].nome, quantidade=Decimal('4'), valor_unitario=parts[0].preco_venda, desconto=Decimal('0'), total=parts[0].preco_venda * Decimal('4')),
    ]
    db.session.add_all(budget_items)
    recalculate_budget_totals(budget)

    db.session.commit()
