# ERP Auto Center

Sistema web para gestão de oficinas mecânicas. Centraliza clientes e veículos, orçamento e aprovação digital, ordens de serviço, agenda e pátio, inspeções, estoque, compras, financeiro gerencial e documentos fiscais.

## Stack

- Python 3.11+
- Flask 3 e SQLAlchemy 2
- MySQL 8.4/InnoDB em desenvolvimento e produção
- SQLite em memória somente nos testes unitários
- Alembic/Flask-Migrate para evolução do banco
- Jinja, CSS e JavaScript sem framework no frontend
- ReportLab para documentos PDF

## Preparação local

1. Copie `.env.example` para `.env` e troque as credenciais e a chave secreta.
2. Inicie um MySQL 8.4 e crie o banco indicado em `DATABASE_URL`.
3. Instale as dependências: `python -m pip install -r requirements-dev.txt`.
4. Aplique o schema: `flask --app run.py db upgrade`.
5. Para uma instalação vazia, defina `INITIAL_ADMIN_PASSWORD` com pelo menos 12 caracteres e execute uma vez: `flask --app run.py seed`.
6. Inicie: `flask --app run.py run --debug`.

`AUTO_CREATE_SCHEMA` deve permanecer `false`. Bancos anteriores ao Alembic devem ser verificados e marcados uma única vez com `flask --app run.py adotar-baseline`; consulte os documentos de entrega antes de executar isso em dados reais.

## Qualidade

```text
python -m ruff check app tests
python -m pytest
python -m pytest --cov=app --cov-report=term-missing
```

O workflow em `.github/workflows/quality.yml` também testa upgrade, downgrade e novo upgrade das migrations em MySQL.

## Operação

- Migração de dados: **Configurações → Migração de dados**. Importação em massa de CSV,
  HTML, XLS e XLSX, incluindo ordens de serviço, revisão de colunas e relatório de resultados. Veja [guia de migração](docs/migracao-dados.md)
  para instalação, formatos e regras. Execute `flask --app run.py jobs-worker --watch` para manter a fila ativa.

- Saúde: `GET /api/health` verifica aplicação e banco.
- Logs: JSON em `stdout`, com `X-Request-ID` em cada resposta.
- Fila: `flask --app run.py jobs-worker --once` processa uma tarefa pendente; em produção, execute continuamente por um supervisor.
- Backup: `scripts/backup_mysql.sh` cria dump transacional compactado.
- Restauração: `scripts/restore_mysql.sh caminho/arquivo.sql.gz`.

Leia [Operação em produção](docs/operacao-producao.md) antes da primeira implantação.

## Segurança

### Cloudflare Turnstile no login

O login web usa Cloudflare Turnstile e valida o token no servidor. Em desenvolvimento,
o projeto usa automaticamente as chaves de teste oficiais da Cloudflare, válidas em
`localhost` e `127.0.0.1`. Em produção, crie um widget Turnstile no painel da Cloudflare
e configure obrigatoriamente:

```env
TURNSTILE_SITE_KEY=sua-chave-publica
TURNSTILE_SECRET_KEY=sua-chave-secreta
```

Cadastre no widget apenas os hostnames reais da aplicação. Não use as chaves de teste
em produção. A autenticação em duas etapas continua independente: quando ativada para
um usuário, o código do autenticador é solicitado em uma segunda tela após o CAPTCHA,
usuário e senha.

Configure `CNPJA_API_KEY` somente se quiser priorizar a API autenticada da CNPJá; sem
essa variável, a consulta usa os provedores públicos de contingência. A chave que já
esteve no histórico do Git deve ser revogada no provedor. Para publicar a landing em
`website/`, use `LANDING_ENV=production` e uma `LANDING_SECRET_KEY` exclusiva com pelo
menos 32 caracteres.

- CSRF nos formulários e chamadas mutáveis.
- Cookies `HttpOnly`, `SameSite=Lax` e `Secure` em produção.
- Content Security Policy e cabeçalhos defensivos.
- Rate limit persistente de login.
- Permissões por capacidade, além dos papéis de usuário.
- MFA TOTP opcional em **Perfil → Segurança da conta**.
- Fotos de inspeção validadas, redimensionadas, normalizadas e servidas apenas a usuários autenticados.
- Auditoria para operações sensíveis de estoque, aprovação e conciliação.

Nunca versione `.env`, certificados, tokens fiscais, XMLs reais, backups ou anexos de clientes.
