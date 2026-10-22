# LS Hub ERP Auto Center: contexto completo do sistema

Documento para passar a outra IA ou a outro desenvolvedor o que o sistema é, como funciona e em que estado está.
Gerado a partir do código do repositório `lsanzz/ERP-Auto-Center` (commit `fdbeafb`, out/2026).

---

## 1. O que é

**LS Hub** é um ERP web para **oficinas mecânicas / auto centers no Brasil**. Ele cobre o ciclo inteiro:
cliente → veículo → agendamento → orçamento → ordem de serviço (O.S.) → pátio → estoque → financeiro → nota fiscal.

- Idioma da interface e do código de negócio: **português do Brasil**.
- Hoje roda **uma empresa por instalação/banco** (não é multi-tenant).
- Em produção atende uma oficina real, com dados migrados do sistema anterior (**vhsys**):
  ~5.108 O.S., ~14.007 lançamentos financeiros, ~3.764 clientes, ~3.925 produtos.
- Há também um **site comercial** separado (`marketing.py` + `website/`) que vende o produto (planos Essencial, Profissional e Gestão) e coleta pedidos de demonstração.
- Domínio do app: `app.lshub.com.br`.

## 2. Stack e infraestrutura

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.11, **Flask 3.1** com blueprints |
| ORM / banco | Flask-SQLAlchemy + **MySQL 8.4** (InnoDB, utf8mb4) via `pymysql`; SQLite em memória só nos testes |
| Migrations | Alembic / Flask-Migrate (`migrations/`), aplicadas com `flask --app run.py db upgrade` |
| Formulários / CSRF | Flask-WTF |
| PDFs | ReportLab (O.S., orçamentos) |
| Planilhas / XML | openpyxl, xlrd, lxml, defusedxml (NF-e) |
| MFA | pyotp (TOTP) |
| IA | SDK `groq` (modelo padrão `openai/gpt-oss-120b`) |
| Front | Templates Jinja2 server-side (`app/templates/`), CSS próprio (`theme.css`, `lshub-ui.css`, `responsive.css`), JS leve, sem SPA |
| Deploy | **cPanel + Passenger** (`passenger_wsgi.py`) ou Gunicorn; worker de jobs `flask --app run.py jobs-worker` |
| Testes | pytest (cerca de 280 testes), ruff, cobertura mínima de 45% |

Desenvolvimento local: `docker-compose.yml` sobe o MySQL. Backup e restauração ficam em `scripts/backup_mysql.sh` e `scripts/restore_mysql.sh` (retenção de 14 dias).

## 3. Estrutura de pastas

```
run.py / passenger_wsgi.py   entrada da aplicação
app/
  __init__.py        create_app, registro de blueprints, segurança, cabeçalhos
  models.py          modelos principais (usuários, clientes, O.S., financeiro, estoque, fiscal...)
  web.py             maior módulo (~2.900 linhas): telas de clientes, O.S., orçamentos, financeiro, produtos, fiscal, configurações
  api.py             API JSON REST (/api/...)
  services.py        regras de negócio (totais da O.S., itens, liquidação, numeração)
  auth.py / security.py  login, sessão, MFA, perfis e permissões
  assistant/         assistente de IA (llm.py, tools.py, routes.py)
  fleet/             veículos, quilometragem, histórico de dono
  scheduling/        agenda, recursos (boxes/elevadores), pátio (kanban de etapas)
  operations/        inspeção com fotos, aprovação de orçamento por link, reserva de peças, estoque, auditoria, garantia
  management.py      /gestao: conciliação bancária, compras/reposição, estornos de estoque
  business_reports.py balancete, calendário financeiro, recibo, histórico central
  finance_overview.py indicadores e DRE gerencial
  fiscal.py          NF-e de peças, NFS-e da O.S., Focus NFe
  uninfe_*.py        integração UniNFe (emissor fiscal Windows) via conector HTTPS
  data_migration/    importação de dados de outros sistemas (CSV/planilha) com retomada
  xml_import.py      importação de NF-e de compra (entrada de mercadoria)
  cnpj.py / cep.py   consulta CNPJ (CNPJá), CEP
  jobs.py            fila assíncrona simples (tabela async_jobs)
  system_admin.py    painel do dono do sistema (/sistema), separado dos usuários da oficina
  templates/ static/
scripts/             importação/sincronização vhsys, reconciliação, backup
tests/               pytest
docs/                documentação por entrega/tema
website/ marketing.py  site comercial público (app Flask separado)
graphify-out/        grafo de conhecimento do código (ferramenta graphify)
```

## 4. Perfis e permissões

`User.role` define as permissões (`app/auth.py`, `ROLE_PERMISSIONS`):

| Perfil | Pode |
|---|---|
| ADMINISTRADOR | tudo (`*`) |
| RECEPCIONISTA | clientes, veículos, agenda, orçamentos, O.S. (ver, gerenciar, avançar), aprovações |
| MECANICO | ver painel, veículos, agenda, O.S.; avançar O.S.; inspeções; apontamento de horas |
| ESTOQUISTA | estoque (ver, movimentar), compras |
| FINANCEIRO | financeiro (ver, liquidar, conciliar), relatórios |

As rotas usam os decorators `@login_required`, `@permission_required('x.y')` e `admin_required`. O MFA (TOTP) é opcional por usuário. A senha precisa ter no mínimo 12 caracteres. O painel `/sistema` usa outra tabela (`system_admins`) e outro login.

## 5. Modelo de dados (principais entidades)

- **Client**: nome, CPF/CNPJ, contatos, endereço. Tem vários **Vehicle** (`fleet/models.py`: placa, modelo, km, com `OdometerReading` e `VehicleOwnershipHistory`).
- **Service** (catálogo de mão de obra) e **Product** (peças, com estoque, NCM/CFOP, custo e preço).
- **Employee** (mecânicos/responsáveis) e **User** (login).
- **PaymentMethod**: Dinheiro, Pix, cartões etc.; cada uma pode ter conta bancária padrão e prazo.
- **BankAccount**: contas com saldo (ex.: "Dinheiro" e "JURIDICA").
- **Budget** e **BudgetItem** (orçamento). Status: `ABERTO`, `APROVADO`, `REPROVADO`, `CANCELADO`. Pode virar O.S. A aprovação pode ser feita pelo cliente via link (`/operacao/aprovar/<token>`).
- **WorkOrder** (O.S.):
  - Campos: `numero` (único), `client_id`, `vehicle_id`, `placa`, `employee_id`, `status`, `current_stage`, datas de entrada e saída, `promised_at`, totais (peças, serviços, desconto, geral), `problema_relatado`, `laudo`, `tipo_atendimento` (INTERNO/EXTERNO/GARANTIA), `emitir_nota`, `estoque_baixado`. Tem controle de versão otimista (`version`).
  - Status: `ABERTA`, `EM_ANDAMENTO`, `AGUARDANDO_PECA`, `FINALIZADA`, `ENTREGUE`, `CANCELADA`.
  - Etapas do pátio (`current_stage`): `RECEPCAO`, `DIAGNOSTICO`, `AGUARDANDO_APROVACAO`, `AGUARDANDO_PECA`, … (lista em `scheduling/services.py`).
  - Filhos: `WorkOrderItem` (`item_type` SERVICO/PECA, quantidade, valor, desconto), `WorkOrderPayment` (pagamento dividido em várias formas, cada uma com parcelas), `WorkOrderChecklist`, `WorkOrderStatusHistory`, `WorkOrderStageHistory`, `VehicleInspection` + fotos, `StockReservation`, `ServiceWarranty`.
- **FinancialEntry** (contas a pagar e a receber):
  - Campos: `entry_type` (`RECEBER`/`PAGAR`), `valor`, `vencimento`, `status` (`PENDENTE` → liquidado), parcela n/total, `payment_method_id`, `bank_account_id`, `reference_type`/`reference_id` (ex.: `OS`, `XML_NFE`, `ENTRADA_ESTOQUE`), categoria, plano de contas, centro de custo.
  - Campos da baixa: `valor_baixa`, juros, desconto, taxa, acréscimo. A baixa parcial existe ("Baixar conta").
  - Tem controle de versão otimista.
- **ChartOfAccount**, **CostCenter**, **BankTransaction** + **BankReconciliation** (conciliação por CSV).
- Estoque: **StockEntry**/**StockEntryItem** (entrada por XML), **InventoryMovement** (com estorno), **StockLocation**, **InventoryCount**, **PurchaseRequest** (reposição).
- Fiscal: **FiscalDocument**, **FiscalApiConfig**, **UniNFeSubmission**, **UniNFeRelayTask**, **XmlInvoiceImport**.
- Agenda: **Appointment** (status `AGENDADO`, `CONFIRMADO`, `EM_ATENDIMENTO`, `CONCLUIDO`, `CANCELADO`, `NAO_COMPARECEU`) e **WorkshopResource**.
- Outros: **AuditEvent** (auditoria de quem mudou o quê; guarda os nomes dos campos, não os valores), **AsyncJob**, **CommissionRule**/**CommissionEntry**, **SystemSettings** (dados da empresa e parâmetros fiscais).

## 6. Telas e rotas (web)

| Área | Rotas principais |
|---|---|
| Login / MFA | `/login`, `/login/mfa`, `/logout` |
| Painel | `/dashboard`: saldos das contas, indicadores |
| Clientes | `/clientes`, `/clientes/novo`, `/clientes/<id>`, editar, excluir, `/clientes/buscar` (autocomplete) |
| Veículos | `/veiculos`, `/veiculos/novo`, `/veiculos/<id>`, `/veiculos/buscar`, quilometragem, situação; `/consultas/placa` (API externa de placas) |
| Agenda | `/agenda`, `/agenda/novo`, `/agenda/painel`, `/agenda/recursos`, converter agendamento em O.S. |
| Pátio | `/agenda/patio`: kanban das O.S. abertas por etapa/coluna |
| Orçamentos | `/orcamentos`, novo, editar, itens, aprovar, converter em O.S., solicitar aprovação por link |
| O.S. | `/os`, `/os/nova`, `/os/<id>`, editar, itens, status, responsável, copiar, finalizar, excluir, PDF, `/os/catalogo` (busca de serviços/peças), `lancar-contas`, `lancar-estoque`, `atualizar-recebimento`, nota (preparar/emitir/preview), inspeção com fotos, reservar/liberar peças |
| Financeiro | `/financeiro`, `/financeiro/novo`, liquidar, estornar, remover, importações (XML, outro sistema), recibo, balancete, calendário |
| Produtos / Serviços | CRUD; importação de produtos por XML de NF-e; `/entrada-mercadoria/importar` |
| Estoque | `/operacao/estoque`, entrada, ajuste; `/gestao` (reposição, recebimento de compra, estorno de movimento) |
| Banco | `/gestao/banco/importar`, conciliar |
| Fiscal | `/fiscal` (central), NF-e de peças, consultar, cancelar, XML; integração Focus NFe e UniNFe |
| Relatórios | `/relatorios`, exportar XML; `/historico` (histórico central + CSV) |
| Configurações | `/configuracoes`: empresa, certificado, operação, perfil, usuários, MFA, `/configuracoes/migracao` (importação de dados) |
| Funcionários / Formas de pagamento | CRUD |
| Assistente IA | `/assistente/nova`, `/mensagem`, `/confirmar/<draft>`, `/cancelar/<draft>` |
| Admin do sistema | `/sistema/login`, `/sistema/admin`, `/sistema/admin/integracao` |

A **API JSON** (`app/api.py`, prefixo `/api`) tem sessão (`POST/DELETE /api/session`), `/api/health`, `/api/dashboard`, CRUD de clientes, veículos (por placa), produtos, serviços, funcionários, formas de pagamento, contas bancárias, orçamentos, O.S. e financeiro, além de ações (aprovar, converter, finalizar, liquidar/quitar, importar XML). A API do conector UniNFe fica em `/api/uninfe-connector/tasks...`.

## 7. Fluxos de negócio importantes

1. **Atendimento típico:** agendamento (opcional) → orçamento (opcional, com aprovação do cliente por link) → **O.S.** com cliente + veículo + itens (serviços e peças) → a O.S. anda pelas etapas do pátio → finaliza → **lança contas** (gera `FinancialEntry` RECEBER por forma de pagamento e parcela) → **baixa o estoque** das peças → entrega → nota fiscal (opcional).
2. **Recebimento direto da O.S.:** os pop-ups na própria tela da O.S. lançam e liquidam o recebimento, sem ir ao Financeiro.
3. **Roteamento automático de conta bancária:** pagamento em **Dinheiro** cai na conta "Dinheiro"; **Pix e cartão** caem na conta "JURIDICA". Recebimento sem conta escolhida usa a conta padrão da forma de pagamento.
4. **Liquidação (baixa):**
   - É idempotente e trava o lançamento no MySQL, então repetir a baixa não altera o saldo duas vezes.
   - Atualiza o saldo da conta bancária. Aceita juros, desconto, taxa e acréscimo, e a baixa pode ser parcial.
   - Correções se fazem por **estorno auditável**, nunca apagando o lançamento.
5. **Proteções:**
   - Não se exclui O.S. com recebimento já liquidado.
   - Valores negativos ou inválidos são rejeitados.
   - Controle de versão otimista em O.S. e lançamentos.
   - CSRF em todos os formulários e `Cache-Control: no-store` nas páginas.
6. **Pátio:** mostra só a **O.S. aberta** (as ~5.100 históricas ficam de fora).
7. **Desempenho:** cliente, veículo e peça são buscados por **autocomplete** e não carregados em listas completas. As páginas de O.S. pesam cerca de 70 a 80 KB.
8. **Compras:** importar o XML da NF-e do fornecedor gera a entrada de estoque e a conta a pagar (`XML_NFE`).

## 8. Assistente de IA (já existe)

Fica em `app/assistant/` e aparece como um widget nas telas (`_assistant.html`).

- **Provedor:** Groq (`GROQ_API_KEY`, `GROQ_MODEL`, padrão `openai/gpt-oss-120b`), via function calling. Pode ser desligado com `ASSISTANT_ENABLED=0`.
- **Princípio:** a IA **nunca grava**. Ela só **propõe** um rascunho (draft na sessão), e o usuário clica em **Confirmar**. Só então o servidor grava, usando os mesmos serviços das telas e registrando auditoria.
- **Ferramentas** (`tools.py`): `buscar_cliente`, `buscar_veiculo_por_placa`, `buscar_catalogo`, `listar_funcionarios`, `listar_formas_pagamento`, `consultar_os`, `relatorio_periodo`, `contas_vencendo`, `propor_os`, `propor_alteracao_os`.
- **Regras do prompt:**
  - Não inventar ids nem valores; perguntar quando houver ambiguidade.
  - Usar o preço do catálogo.
  - Converter datas relativas usando a data de hoje.
  - Juntar placas ditadas por voz (ex.: "d s p 2 e 32" → `DSP2E32`). A placa também é detectada por regex.
- **Limites:** até 6 rodadas de ferramenta por mensagem; histórico curto de 6 mensagens; 12 mensagens por minuto por usuário (contador em memória).
- **Ainda não faz:** criar ou liquidar lançamentos financeiros, agenda e orçamento; relatórios além de período e vencimentos.

## 9. Integrações externas e variáveis de ambiente

| Integração | Variáveis |
|---|---|
| Banco | `DATABASE_URL`, `AUTO_CREATE_SCHEMA` (deixar false em produção) |
| App | `SECRET_KEY`, `APP_ENV`, `TRUSTED_HOSTS`, `INITIAL_ADMIN_PASSWORD` |
| IA (Groq) | `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_REASONING`, `ASSISTANT_ENABLED` |
| Fiscal Focus NFe | `FOCUS_NFE_TOKEN_PRINCIPAL` (ou o configurado em `/sistema/admin/integracao`) |
| Fiscal UniNFe (Windows) | `UNINFE_TRANSPORT`, `UNINFE_CONNECTOR_ID`, `UNINFE_CONNECTOR_TOKEN` |
| CNPJ / CPF | `CNPJA_API_KEY`, `CPFHUB_API_KEY`, `CPFHUB_BASE_URL` |
| Placas | `PLATE_API_URL`, `PLATE_API_KEY`/`TOKEN`, `PLATE_API_HEADER`, `PLATE_API_TIMEOUT` |
| Site comercial | `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` (captcha Cloudflare) |
| Jobs | `ASYNC_EXTERNAL_CALLS` |

O `.env` fica no servidor e **nunca** vai para o Git.

## 10. Operação em produção (resumo de `docs/operacao-producao.md`)

- Sequência de deploy:
  1. Fazer backup.
  2. Testar a migration em homologação.
  3. Pausar gravações.
  4. `db upgrade` uma única vez.
  5. Subir a aplicação e o worker.
  6. Checar `/api/health`.
- Nunca usar `db.create_all()` em produção.
- Monitorar: HTTP 500, `/api/health`, disco, conexões MySQL, jobs com status `FALHOU`, validade do certificado fiscal e idade do backup (menos de 26 h).
- Fazer um teste de restauração do backup todo mês.

## 11. Estado atual e pendências conhecidas

- Sistema **funcional em produção** para uso manual, com os testes automatizados passando.
- **Pendências de dados e de negócio** (decisão do dono):
  1. Trocar a senha do usuário admin (estava fraca, o que é um risco de segurança).
  2. Validar R$ 699.341,77 em contas a pagar que vieram "Em aberto" do vhsys.
  3. 304 O.S. antigas de 2023 estão sem forma de pagamento (os extratos não cobriam esse período).
  4. Há clientes duplicados (ex.: "ALEXANDRE BMW" e "ALEXANDRE BMW 320I"), que precisam ser consolidados.
  5. 122 produtos estão com estoque negativo e precisam de ajuste.
- **Planejado:**
  - Ampliar o assistente de IA: voz no navegador, rascunhos de lançamentos financeiros, agenda e orçamento, e mais relatórios prontos.
  - Medir a precisão do assistente com frases geradas a partir das O.S. reais.
- **Limites técnicos:**
  - `web.py` é grande demais e concentra muita regra; o ideal é extrair as regras para `services`.
  - Os testes rodam em SQLite, então os locks do MySQL precisam de validação em homologação.
  - A integração fiscal ainda não foi homologada com credenciais reais.
  - Boletos, NFC-e e manifestação de nota ainda não foram implementados.

## 12. Convenções para quem for mexer no código

- Nomes de domínio em português (`numero`, `valor`, `vencimento`, `liquidar`, `estornar`). A infraestrutura fica em inglês.
- Toda mutação de dinheiro, estoque ou documento fiscal deve:
  - passar pelos serviços existentes;
  - registrar `AuditEvent`;
  - ser revertida por estorno, nunca por DELETE.
- Mudança de schema só por migration Alembic em `migrations/versions/`.
- Toda rota precisa de `login_required` ou `permission_required` com a permissão certa do perfil.
- Testes ficam em `tests/` e rodam com `pytest -q`.
- O grafo `graphify-out/` documenta o código. Depois de alterar código, rodar `graphify update .`.
