# Banco de dados relacional

## Banco recomendado para produção
MySQL 8.4 com InnoDB.

O sistema exige MySQL fora dos testes. SQLite é aceito somente quando a aplicação é criada explicitamente em modo de teste.

## Configuração do MySQL
- engine InnoDB para transações, chaves estrangeiras e locks de linha
- charset `utf8mb4` e collation `utf8mb4_unicode_ci`
- bloqueios `SELECT FOR UPDATE` nas baixas e reservas concorrentes

## Configuração de conexão
O sistema lê a conexão pela variável de ambiente `DATABASE_URL`.

Exemplo:
```env
DATABASE_URL=mysql+pymysql://erp:SENHA@127.0.0.1:3306/erp_auto_center?charset=utf8mb4
```

Sem `DATABASE_URL`, a inicialização é recusada para impedir uso acidental de outro banco.

## Tabelas principais
- users
- employees
- clients
- services
- products
- budgets
- budget_items
- work_orders
- work_order_items
- work_order_checklists
- financial_entries
- payment_methods
- bank_accounts
- xml_invoice_imports

## Observações de compatibilidade
- novas instalações usam `flask db upgrade`
- instalações legadas adotam a baseline após validação em homologação
- `db.create_all()` permanece temporariamente como ponte compatível quando `AUTO_CREATE_SCHEMA=true`
