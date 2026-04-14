# ERP Auto Center

Sistema web para oficina auto center com foco em ordens de serviço, clientes, financeiro e importação de XML.

## Novidades desta versão
- suporte oficial a PostgreSQL via `DATABASE_URL`
- SQLite continua disponível para testes locais rápidos
- `docker-compose.yml` para subir PostgreSQL localmente
- conexão com `pool_pre_ping` para evitar conexões quebradas
- compatível com URLs `postgres://` e `postgresql://`

## Execução rápida com PostgreSQL
```bash
docker compose up -d
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Ajuste a variável `DATABASE_URL` no `.env` quando necessário.

Exemplo:
```env
DATABASE_URL=postgresql://postgres:1905@localhost:5432/erp_oficina
SECRET_KEY=troque-esta-chave
```

## Execução com SQLite
Se `DATABASE_URL` não estiver definido, o sistema continua usando SQLite automaticamente.

## Credenciais demo
- admin / admin123
- mecanico / mecanico123
