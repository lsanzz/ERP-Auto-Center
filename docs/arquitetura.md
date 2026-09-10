# Arquitetura do sistema

## Stack atual
- Flask
- Flask-SQLAlchemy
- MySQL 8.4 em produção e desenvolvimento
- SQLite apenas para testes unitários isolados
- ReportLab para PDFs

## Estratégia de banco
O sistema usa MySQL/InnoDB com `utf8mb4` e recebe a conexão por `DATABASE_URL`.

### Ambientes
- desenvolvimento/homologação/produção: MySQL 8.4
- testes unitários: SQLite em memória, explicitamente configurado

## Fluxo de inicialização
1. lê `DATABASE_URL`
2. valida e normaliza a URL para `mysql+pymysql`
3. inicia SQLAlchemy com `pool_pre_ping`
4. cria tabelas ausentes com `db.create_all()`
5. aplica pequenos ajustes de schema necessários
6. executa seed inicial

## Infraestrutura sugerida
- aplicação Flask
- MySQL 8.4 com tabelas InnoDB e charset utf8mb4
- backup diário do banco
- storage local ou nuvem para PDFs futuros
