# Banco de dados relacional

## Banco recomendado para produção
PostgreSQL.

O sistema agora suporta PostgreSQL como banco principal para uso real da oficina e mantém SQLite apenas como fallback para desenvolvimento local rápido.

## Motivos para usar PostgreSQL
- melhor concorrência para múltiplos usuários
- integridade transacional forte
- melhor escalabilidade para financeiro, dashboards, fiscal e BI
- compatibilidade futura com relatórios e integrações mais complexas

## Configuração de conexão
O sistema lê a conexão pela variável de ambiente `DATABASE_URL`.

Exemplo:
```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/erp_auto_center
```

Se a variável não estiver definida, usa:
```text
sqlite:///instance/erp_auto_center.db
```

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
- `db.create_all()` funciona tanto em SQLite quanto PostgreSQL
- a rotina de atualização de schema reconhece o dialeto PostgreSQL
- URLs antigas com `postgres://` são convertidas automaticamente para `postgresql://`
