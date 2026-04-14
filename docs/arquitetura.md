# Arquitetura do sistema

## Stack atual
- Flask
- Flask-SQLAlchemy
- PostgreSQL em produção
- SQLite como fallback local
- ReportLab para PDFs

## Estratégia de banco
O sistema foi preparado para trabalhar com PostgreSQL usando `DATABASE_URL`, sem remover a compatibilidade com SQLite.

### Ambientes
- desenvolvimento rápido: SQLite
- homologação/produção: PostgreSQL

## Fluxo de inicialização
1. lê `DATABASE_URL`
2. normaliza URL PostgreSQL legada (`postgres://`)
3. inicia SQLAlchemy com `pool_pre_ping`
4. cria tabelas ausentes com `db.create_all()`
5. aplica pequenos ajustes de schema necessários
6. executa seed inicial

## Infraestrutura sugerida
- aplicação Flask
- PostgreSQL 16
- backup diário do banco
- storage local ou nuvem para PDFs futuros
