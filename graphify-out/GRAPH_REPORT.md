# Graph Report - erp-auto-center  (2026-10-23)

## Corpus Check
- 221 files · ~164,380 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 56 file(s) not represented in the graph (top: .css 21, .woff2 12, (none) 9)

## Summary
- 2075 nodes · 6741 edges · 169 communities (95 shown, 74 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 697 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `15a8341a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- api.py
- test_structure.py
- web.py
- Client
- fiscal.py
- current_user
- test_review_regressions.py
- DataMigrationTest
- parse_decimal
- create_financial_entries
- re
- llm.py
- operations/routes.py
- ERPAppTestCase
- service.py
- WorkOrder
- data_migration/routes.py
- uninfe_connector.py
- scheduling/routes.py
- UniNFePreparationTests
- FinancialEntry
- app.py
- system_admin.py
- AssistantTest
- business_reports.py
- issue
- uninfe_relay.py
- uninfe_xml.py
- login_required
- pdfs.py
- readers.py
- get_config
- hook.cjs
- apply_protocol
- uninfe_events.py
- S-001 Painel do pátio (Floor)
- management.py
- security.py
- create_app
- site.js
- os
- json
- S-000 {{screen_name}}
- test_uninfe_migrations.py
- AuditEvent
- subscription_status
- sqlalchemy
- app/models.py
- Entrega 01 — Base técnica e cadastro de veículos
- Migração de dados
- BusinessReportsTest
- Integração UniNFe — estado de implementação
- Plano de estruturação e implementação — ERP Automotivo
- 7. Plano de implementação por fases
- Clone requirements: Torque
- configure_security
- 20260906_03_operations.py
- C-000 {{neutral_name}}
- 20260907_05_company_profile.py
- alembic
- 20260922_11_uninfe.py
- Operação em produção
- 5. Modelo de dados planejado
- Status: Torque
- E-000 {{entity_name}}
- Session s{{NN}} · {{date}}
- Site comercial LS Hub
- MarketingTests
- client-picker.js
- Arquitetura do sistema
- Banco de dados relacional
- Topic: {{topic_name}}
- ui.js
- vehicle-selector.js
- Entrega 03 — Operação digital integrada
- Fiscal, financeiro e histórico — inventário de entrega
- 9. Backlog de indicadores
- Rules: Pátio
- FL-000 {{flow_name}}
- Responsividade do ERP
- Revisão do sistema — 16/09/2026
- 20260922_13_uninfe_dispatch.py
- API
- Entrega 02 — MySQL, agenda e pátio
- 8. Roadmap sugerido
- Implications for the clone
- 20261022_21_system_admin_mfa.py
- Direção da homepage — revisão monocromática
- 15. Decisões que devem ser fechadas antes de cada marco
- 4. Arquitetura-alvo
- Production barriers: Torque
- Findings
- Torque: reverse engineering knowledge base
- SessionClient
- ReviewRegressionTest
- cep.js
- 11. Estratégia de testes
- 3. Diagnóstico da base atual
- Rules: {{area}}
- Topic: hidden writes
- json
- app/services.py
- 20260907_07_system_admin.py
- 20260909_08_management_foundation.py
- app/__init__.py
- 20260922_12_uninfe_submissions.py
- datetime
- 20261021_18_work_order_details.py
- 20261022_19_assistant_states.py
- 2026-10-21-painel-do-pa-tio-tre-s-lsanzz.md
- nfe/README.md
- service-worker.js
- CLAUDE.md
- painel-dono-focus.md
- 00-charter.md
- endpoints.md
- parity.md
- permissions.md
- tokens.md
- glossary.md
- coverage.md
- features.md
- screens.md
- questions.md
- environment.md
- fixtures.md
- sources.md
- telas.md
- backup_mysql.sh
- bootstrap.sh
- restore_mysql.sh
- .trail/README.md
- Contrato de Licença de Uso de Software (SaaS) — LS Hub
- issue
- comercial/README.md
- Política de Privacidade — LS Hub (sistema)
- Implantação de uma oficina nova
- BusinessReadinessTest
- Cobrança das oficinas
- Homologação fiscal (NF-e de peças e NFS-e de serviços)
- Suporte ao cliente — Anexo III
- get_system_settings
- create_app
- SystemAdminPrivacyTest
- 20260914_10_data_migration.py
- 20260923_14_uninfe_cancel.py
- 20260923_15_uninfe_event_archive.py
- 20261022_20_subscription.py

## God Nodes (most connected - your core abstractions)
1. `WorkOrder` - 171 edges
2. `login_required()` - 129 edges
3. `Client` - 98 edges
4. `post()` - 92 edges
5. `FinancialEntry` - 89 edges
6. `create_app()` - 79 edges
7. `current_user()` - 78 edges
8. `permission_required()` - 73 edges
9. `parse_decimal()` - 67 edges
10. `DataMigrationTest` - 66 edges

## Surprising Connections (you probably didn't know these)
- `Fase 1 — Veículo e prontuário (2 a 3 semanas)` --references--> `Vehicle`  [INFERRED]
  docs/plano-estruturacao-implementacao.md → app/fleet/models.py
- `Site comercial LS Hub` --references--> `create_app()`  [INFERRED]
  docs/site-comercial.md → app/__init__.py
- `Integração UniNFe — estado de implementação` --references--> `ManagedCompany`  [INFERRED]
  docs/integracao-uninfe.md → app/models.py
- `Integração UniNFe — estado de implementação` --references--> `SystemSettings`  [INFERRED]
  docs/integracao-uninfe.md → app/models.py
- `14. Primeira fila de execução` --references--> `Appointment`  [INFERRED]
  docs/plano-estruturacao-implementacao.md → app/scheduling/models.py

## Import Cycles
- None detected.

## Communities (169 total, 74 thin omitted)

### Community 0 - "api.py"
Cohesion: 0.06
Nodes (79): api_login_required(), wrapped(), api_roles_required(), decorator(), wrapped(), as_json(), bank_account_resource(), bank_accounts_collection() (+71 more)

### Community 1 - "test_structure.py"
Cohesion: 0.05
Nodes (39): _alternatives(), buscar_catalogo(), buscar_cliente(), buscar_veiculo_por_placa(), _catalog_match(), consultar_os(), contas_vencendo(), edit_draft_items() (+31 more)

### Community 2 - "web.py"
Cohesion: 0.08
Nodes (43): login_user(), safe_next_url(), login_is_rate_limited(), clients_edit(), clients_index(), clients_new(), concurrent_change(), _decimal_input_value() (+35 more)

### Community 3 - "Client"
Cohesion: 0.10
Nodes (9): Client, PaymentMethod, Service, User, encrypt_secret(), seed_database(), FormLookupTest, ManagementTest (+1 more)

### Community 4 - "fiscal.py"
Cohesion: 0.16
Nodes (19): cell(), build_focus_nfe_payload(), build_focus_nfse_payload(), build_internal_xml(), row(), decode_payload(), _digits(), encode_payload() (+11 more)

### Community 5 - "current_user"
Cohesion: 0.11
Nodes (39): cancel(), new_conversation(), current_user(), wrapped(), permission_required(), decorator(), wrapped(), role_required() (+31 more)

### Community 6 - "test_review_regressions.py"
Cohesion: 0.05
Nodes (38): _deep_text(), _format_cnpj_cpf(), _format_date(), _format_datetime(), _number(), parse_nfe_xml(), _text(), browser() (+30 more)

### Community 8 - "parse_decimal"
Cohesion: 0.11
Nodes (20): finance_import_xml(), XmlInvoiceImport, register_inventory_change(), add_months(), reconcile_company_config(), parse_date(), parse_decimal(), bank_accounts_edit() (+12 more)

### Community 9 - "create_financial_entries"
Cohesion: 0.16
Nodes (5): create_financial_entries(), default_bank_account_id(), method_account_map(), _plain(), FinanceStockFlowsTest

### Community 10 - "re"
Cohesion: 0.16
Nodes (22): money(), parse_finance_export(), source_date(), normalize(), work_order_status(), work_order_receivable_description(), key(), main() (+14 more)

### Community 11 - "llm.py"
Cohesion: 0.16
Nodes (9): AssistantUnavailable, _context(), enabled(), make_client(), run_turn(), spoken_plate(), inject_assistant(), listar_formas_pagamento() (+1 more)

### Community 12 - "operations/routes.py"
Cohesion: 0.11
Nodes (33): Product, Supplier, BudgetApproval, BudgetApprovalItem, BudgetRevision, InspectionItem, InspectionPhoto, InventoryMovement (+25 more)

### Community 14 - "service.py"
Cohesion: 0.12
Nodes (22): complete_orders(), item_key(), read_detailed_orders(), candidate_client_names(), convert(), DefusedXmlException, digest_for(), existing_keys() (+14 more)

### Community 15 - "WorkOrder"
Cohesion: 0.21
Nodes (3): WorkOrder, deduct_work_order_stock(), VhsysParityTest

### Community 16 - "data_migration/routes.py"
Cohesion: 0.18
Nodes (20): MigrationRow, detail(), get_migration(), index(), private_response(), report(), generate(), retry() (+12 more)

### Community 17 - "uninfe_connector.py"
Cohesion: 0.16
Nodes (11): collect_return(), _directory(), _key(), publish_file(), publish_invoice(), _read(), request_situation(), Client (+3 more)

### Community 18 - "scheduling/routes.py"
Cohesion: 0.11
Nodes (25): Employee, build_floor(), _card(), _elapsed(), Appointment, WorkOrderStageHistory, WorkshopResource, board() (+17 more)

### Community 19 - "UniNFePreparationTests"
Cohesion: 0.14
Nodes (7): apply_invoice_form(), UniNFeSubmission, consult(), access_key(), prepare(), UniNFePreparationTests, UniNFeStorageTests

### Community 20 - "FinancialEntry"
Cohesion: 0.07
Nodes (33): area_path(), dashboard_charts(), financial_overview(), home_context(), render_finance(), entry_description(), entry_party(), imported_details() (+25 more)

### Community 21 - "app.py"
Cohesion: 0.11
Nodes (17): csrf_error(), demonstration(), _env_list(), favicon(), features(), _first_form_value(), _form_options(), health() (+9 more)

### Community 22 - "system_admin.py"
Cohesion: 0.17
Nodes (15): change_password(), current_system_admin(), dashboard(), _failures(), hide_from_unknown_networks(), integration(), _ip_allowed(), login() (+7 more)

### Community 23 - "AssistantTest"
Cohesion: 0.14
Nodes (3): AssistantTest, propose(), FakeCompletions

### Community 24 - "business_reports.py"
Cohesion: 0.26
Nodes (7): balance(), finance_calendar(), history(), net_expression(), period(), receipt(), report_data()

### Community 26 - "uninfe_relay.py"
Cohesion: 0.19
Nodes (12): UniNFeRelayTask, authenticate(), credentials(), enqueue_invoice(), get_task(), list_tasks(), private_response(), problem() (+4 more)

### Community 27 - "uninfe_xml.py"
Cohesion: 0.13
Nodes (12): validate_unsigned(), add(), address(), allocate(), build_invoice(), contribution(), decimal(), digits() (+4 more)

### Community 28 - "login_required"
Cohesion: 0.09
Nodes (46): login_required(), render_fiscal_center(), build_work_order_invoice_payload(), create_or_update_fiscal_document(), get_fiscal_config(), bank_accounts_delete(), budgets_delete(), budgets_index() (+38 more)

### Community 29 - "pdfs.py"
Cohesion: 0.20
Nodes (7): generate_work_order_pdf(), _items_table(), _label_value(), _money(), _p(), _safe(), _section()

### Community 30 - "readers.py"
Cohesion: 0.14
Nodes (5): detect_html_table(), raw_rows(), TableReader, TableStats, text_cell()

### Community 31 - "get_config"
Cohesion: 0.23
Nodes (3): get_config(), save_config(), UniNFeConfigTests

### Community 32 - "hook.cjs"
Cohesion: 0.17
Nodes (11): best(), entry(), fromPkg(), globalRoot(), newer(), onPath(), pkgAbove(), PKGS (+3 more)

### Community 33 - "apply_protocol"
Cohesion: 0.27
Nodes (4): apply_protocol(), document(), response(), UniNFeTransportTests

### Community 34 - "uninfe_events.py"
Cohesion: 0.44
Nodes (6): apply_cancellation_response(), build_cancellation(), cancel(), cancellation_prefix(), collect_cancellation(), UniNFeEventsTests

### Community 35 - "S-001 Painel do pátio (Floor)"
Cohesion: 0.22
Nodes (8): Anatomy, Entry points, Interactions, Not tested, Purpose, Rules, S-001 Painel do pátio (Floor), States

### Community 36 - "management.py"
Cohesion: 0.10
Nodes (19): csv_download(), anonymize_client(), _cell(), export_all(), export_client(), bank_import(), create_purchase(), create_replenishment_request() (+11 more)

### Community 38 - "create_app"
Cohesion: 0.10
Nodes (10): register_job_commands(), jobs_worker(), create_app(), connect(), demonstration(), export_leads(), home_response(), index() (+2 more)

### Community 39 - "site.js"
Cohesion: 0.15
Nodes (14): clamp(), errorSummary, form, header, menu, navigation, onScroll(), revealables (+6 more)

### Community 40 - "os"
Cohesion: 0.18
Nodes (12): digits(), focus_request(), management_token(), NoRedirect, _parse_focus_datetime(), refresh_managed_companies(), sync_company(), ManagedCompany (+4 more)

### Community 41 - "json"
Cohesion: 0.19
Nodes (9): reconcile_os_payments(), read_table(), prepare(), _prepare(), WorkOrderPayment, main(), main(), main() (+1 more)

### Community 42 - "S-000 {{screen_name}}"
Cohesion: 0.14
Nodes (13): Anatomy, Data shown, Entry points, Interactions, Keyboard and accessibility, Microcopy, Not tested, Purpose (+5 more)

### Community 43 - "test_uninfe_migrations.py"
Cohesion: 0.19
Nodes (3): upgrade(), migrations(), UniNFeMigrationTests

### Community 44 - "AuditEvent"
Cohesion: 0.32
Nodes (3): configure_automatic_audit(), audit_before_flush(), AuditEvent

### Community 45 - "subscription_status"
Cohesion: 0.38
Nodes (3): grace_ends(), subscription_status(), inject_subscription()

### Community 46 - "sqlalchemy"
Cohesion: 0.22
Nodes (5): upgrade(), downgrade(), upgrade(), downgrade(), upgrade()

### Community 47 - "app/models.py"
Cohesion: 0.18
Nodes (18): AssistantState, BankReconciliation, BudgetItem, ChartOfAccount, CommissionEntry, CommissionRule, CompanyPartner, CostCenter (+10 more)

### Community 48 - "Entrega 01 — Base técnica e cadastro de veículos"
Cohesion: 0.17
Nodes (10): API e sessão, Banco existente, Banco novo gerenciado por migrações, Disponível nesta entrega, Entrega 01 — Base técnica e cadastro de veículos, Importação do histórico, Instalação e ativação, Próxima entrega (+2 more)

### Community 49 - "Migração de dados"
Cohesion: 0.17
Nodes (11): Cadastros e regras, Como importar, Completar OS a partir de HTML detalhado, Design e validação, Formatos, Migração de dados, Preparar a instalação, Processamento, falhas e operação (+3 more)

### Community 51 - "Integração UniNFe — estado de implementação"
Cohesion: 0.18
Nodes (9): ERP hospedado e UniNFe no Windows, Estado atual, Garantias e limites, Hospedagem (administrador), Windows, Ainda necessário para emissão utilizável, Implementado, Integração UniNFe — estado de implementação (+1 more)

### Community 52 - "Plano de estruturação e implementação — ERP Automotivo"
Cohesion: 0.18
Nodes (11): 10. Segurança, LGPD e confiabilidade, 12. Estratégia de migração, 13. Padrão de entrega de cada história, 1. Objetivo do produto, 2. Princípios de implementação, 6. Fluxos integrados principais, Andamento — 06/09/2026, Fluxo de atendimento (+3 more)

### Community 53 - "7. Plano de implementação por fases"
Cohesion: 0.18
Nodes (11): 7. Plano de implementação por fases, Fase 0 — Estabilização técnica (2 semanas), Fase 1 — Veículo e prontuário (2 a 3 semanas), Fase 2 — Agenda, pátio e capacidade (3 semanas), Fase 3 — Inspeção digital e anexos (3 semanas), Fase 4 — Orçamento e aprovação digital (3 semanas), Fase 5 — Estoque rastreável e compras (4 semanas), Fase 6 — Financeiro gerencial (4 semanas) (+3 more)

### Community 54 - "Clone requirements: Torque"
Cohesion: 0.20
Nodes (9): Build order, Clone requirements: Torque, Core loop, Data model, Launch blockers, Non-goals, Open questions, Problem and users (+1 more)

### Community 57 - "C-000 {{neutral_name}}"
Cohesion: 0.22
Nodes (8): Anatomy, Behavior, C-000 {{neutral_name}}, Keyboard and accessibility, Measurements and tokens, Not tested, States, Variants

### Community 61 - "Operação em produção"
Cohesion: 0.22
Nodes (8): Backup e restauração, Implantação, Monitoramento, Operação em produção, Painel do dono do sistema (privado), Processos, Recuperação, Variáveis desta revisão (22/10/2026)

### Community 62 - "5. Modelo de dados planejado"
Cohesion: 0.25
Nodes (8): 5.1 Clientes e veículos, 5.2 Agenda e operação, 5.3 Inspeção, 5.4 Orçamento e aprovação, 5.5 Estoque e compras, 5.6 Financeiro, 5.7 Auditoria e comunicação, 5. Modelo de dados planejado

### Community 63 - "Status: Torque"
Cohesion: 0.25
Nodes (7): Blocked, Last session, Needs human, Next actions, Residuals, Status: Torque, Summary

### Community 64 - "E-000 {{entity_name}}"
Cohesion: 0.25
Nodes (7): E-000 {{entity_name}}, Fields, Lifecycle, Not tested, Relations, Rules, System fields

### Community 65 - "Session s{{NN}} · {{date}}"
Cohesion: 0.25
Nodes (7): Covered, Decisions, Goal, Incidents, Ledger rows added, Next, Session s{{NN}} · {{date}}

### Community 66 - "Site comercial LS Hub"
Cohesion: 0.25
Nodes (7): Configuração, Consultar os interessados, Entregue, Prévia local, Publicação em lshub.com.br, Site comercial LS Hub, Verificação

### Community 68 - "client-picker.js"
Cohesion: 0.62
Nodes (6): choose(), close(), load(), render(), setClient(), validate()

### Community 69 - "Arquitetura do sistema"
Cohesion: 0.29
Nodes (6): Ambientes, Arquitetura do sistema, Estratégia de banco, Fluxo de inicialização, Infraestrutura sugerida, Stack atual

### Community 70 - "Banco de dados relacional"
Cohesion: 0.29
Nodes (6): Banco de dados relacional, Banco recomendado para produção, Configuração de conexão, Configuração do MySQL, Observações de compatibilidade, Tabelas principais

### Community 71 - "Topic: {{topic_name}}"
Cohesion: 0.29
Nodes (6): Behavior, Not tested, Rules, Scope and configuration, Summary, Topic: {{topic_name}}

### Community 72 - "ui.js"
Cohesion: 0.47
Nodes (4): ask(), buildDialog(), flashesToToasts(), toast()

### Community 73 - "vehicle-selector.js"
Cohesion: 0.67
Nodes (4): choose(), close(), load(), render()

### Community 74 - "Entrega 03 — Operação digital integrada"
Cohesion: 0.33
Nodes (5): Banco MySQL, Entrega 03 — Operação digital integrada, Implementado, Limites que dependem de integração externa, Operação

### Community 75 - "Fiscal, financeiro e histórico — inventário de entrega"
Cohesion: 0.33
Nodes (5): Adicionado, Ainda não entregue / decisões necessárias, Design e validação, Fiscal, financeiro e histórico — inventário de entrega, Preservado no projeto

### Community 76 - "9. Backlog de indicadores"
Cohesion: 0.33
Nodes (6): 9. Backlog de indicadores, Comercial, Estoque, Financeiro, Operação, Qualidade

### Community 77 - "Rules: Pátio"
Cohesion: 0.33
Nodes (5): R-001 Cada box mostra uma única ação, que depende da etapa do carro, R-002 O progresso do box é tempo decorrido sobre tempo vendido, R-003 O KPI de prontos soma o valor a receber, R-004 Estoque baixo lista peças com saldo abaixo do mínimo, Rules: Pátio

### Community 78 - "FL-000 {{flow_name}}"
Cohesion: 0.33
Nodes (5): Branches and errors, Diagram, FL-000 {{flow_name}}, Not tested, Steps

### Community 79 - "Responsividade do ERP"
Cohesion: 0.33
Nodes (5): Direção e referências, Organização, Responsividade do ERP, Roteiro de validação, Validação realizada

### Community 80 - "Revisão do sistema — 16/09/2026"
Cohesion: 0.33
Nodes (5): Correções, Direção visual e referências, Limites e próximos investimentos, Revisão do sistema — 16/09/2026, Validação

### Community 82 - "API"
Cohesion: 0.40
Nodes (4): API, Compatibilidade, Infraestrutura de banco, Variável de ambiente

### Community 83 - "Entrega 02 — MySQL, agenda e pátio"
Cohesion: 0.40
Nodes (4): Configuração MySQL, Entrega 02 — MySQL, agenda e pátio, Funcionalidades, Limites desta entrega

### Community 84 - "8. Roadmap sugerido"
Cohesion: 0.40
Nodes (5): 8. Roadmap sugerido, Marco A — Operação automotiva profissional, Marco B — ERP integrado, Marco C — Plataforma escalável, Marco D — Produto comercial multiempresa

### Community 85 - "Implications for the clone"
Cohesion: 0.40
Nodes (4): Avoid, Copy, Implications for the clone, Improve

### Community 88 - "Direção da homepage — revisão monocromática"
Cohesion: 0.50
Nodes (3): Alvo antes da implementação, Direção da homepage — revisão monocromática, Validação

### Community 89 - "15. Decisões que devem ser fechadas antes de cada marco"
Cohesion: 0.50
Nodes (4): 15. Decisões que devem ser fechadas antes de cada marco, Antes do Marco A, Antes do Marco B, Antes do Marco D

### Community 90 - "4. Arquitetura-alvo"
Cohesion: 0.50
Nodes (4): 4.1 Organização do código, 4.2 Componentes técnicos, 4.3 Preparação para multiempresa, 4. Arquitetura-alvo

### Community 91 - "Production barriers: Torque"
Cohesion: 0.50
Nodes (3): BR-001 WhatsApp messages need Meta business verification, Production barriers: Torque, Summary

### Community 92 - "Findings"
Cohesion: 0.50
Nodes (3): Findings, Problems, Strengths

### Community 93 - "Torque: reverse engineering knowledge base"
Cohesion: 0.50
Nodes (3): How to read, Torque: reverse engineering knowledge base, Where things are

### Community 98 - "11. Estratégia de testes"
Cohesion: 0.67
Nodes (3): 11. Estratégia de testes, Casos financeiros obrigatórios, Pirâmide mínima

### Community 99 - "3. Diagnóstico da base atual"
Cohesion: 0.67
Nodes (3): 3. Diagnóstico da base atual, Capacidades existentes a preservar, Lacunas estruturais

### Community 102 - "json"
Cohesion: 0.23
Nodes (20): _cancel_focus_document(), cancel_focus_nfe(), cancel_focus_nfse(), _consult_focus_document(), consult_focus_nfe(), consult_focus_nfse(), _focus_authorization_header(), _focus_base_url() (+12 more)

### Community 103 - "app/services.py"
Cohesion: 0.16
Nodes (20): confirm(), _friendly_error(), message(), _pop_draft(), _rate_limited(), _state(), Budget, add_budget_item() (+12 more)

### Community 107 - "app/__init__.py"
Cohesion: 0.11
Nodes (6): _normalize_database_url(), _persistent_secret_key(), configure_observability(), JsonFormatter, main(), main()

### Community 109 - "datetime"
Cohesion: 0.16
Nodes (5): DataMigration, MigrationKey, configure_worker(), MigrationWorker, main()

### Community 155 - "Contrato de Licença de Uso de Software (SaaS) — LS Hub"
Cohesion: 0.17
Nodes (12): 10. Limitação de responsabilidade, 11. Disposições gerais, 1. Objeto, 2. Implantação, 3. Preço, pagamento e reajuste, 4. Atraso e suspensão, 5. Nível de serviço (SLA), 6. Obrigações da LS HUB (+4 more)

### Community 157 - "comercial/README.md"
Cohesion: 0.29
Nodes (3): Acordo de Tratamento de Dados Pessoais (DPA) — Anexo II, Pacote comercial do LS Hub, Termos de Uso — LS Hub

### Community 158 - "Política de Privacidade — LS Hub (sistema)"
Cohesion: 0.20
Nodes (10): 1. Papéis, 2. Que dados tratamos e por quê, 3. Com quem compartilhamos, 4. Transferência internacional, 5. Por quanto tempo guardamos, 6. Segurança, 7. Direitos dos titulares, 8. Incidentes (+2 more)

### Community 161 - "Implantação de uma oficina nova"
Cohesion: 0.29
Nodes (7): 1. Antes, 2. Criar o ambiente, 3. Tarefas em segundo plano (obrigatório), 4. Backup (obrigatório), 5. Configuração com o cliente (1 a 2 horas), 6. Depois, Implantação de uma oficina nova

### Community 163 - "Cobrança das oficinas"
Cohesion: 0.33
Nodes (5): Cobrança das oficinas, Como o sistema controla o pagamento, Nota fiscal da mensalidade, Quando automatizar, Rotina mensal sugerida (manual, sem custo de integração)

### Community 164 - "Homologação fiscal (NF-e de peças e NFS-e de serviços)"
Cohesion: 0.33
Nodes (6): Ainda não existe no sistema, Homologação fiscal (NF-e de peças e NFS-e de serviços), Ir para produção, O que você precisa providenciar, Passo a passo no sistema, Testes obrigatórios (marque cada um)

### Community 165 - "Suporte ao cliente — Anexo III"
Cohesion: 0.33
Nodes (6): Canais, Monitoramento (para você saber antes do cliente), Respostas rápidas, Roteiro de atendimento, Severidades e prazos, Suporte ao cliente — Anexo III

### Community 168 - "get_system_settings"
Cohesion: 0.12
Nodes (17): create_parts_fiscal_document(), utility_context(), next_number(), budget_default_date(), get_system_settings(), update_subscription(), format_currency(), budgets_edit() (+9 more)

### Community 170 - "create_app"
Cohesion: 0.09
Nodes (13): configure_upload_limit(), register_database_commands(), seed_command(), upgrade_legacy_vehicle_links(), create_app(), _date_br(), _datetime_br(), _run_schema_updates() (+5 more)

## Knowledge Gaps
- **74 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `WorkOrder` connect `WorkOrder` to `api.py`, `test_structure.py`, `web.py`, `Client`, `fiscal.py`, `current_user`, `test_review_regressions.py`, `DataMigrationTest`, `parse_decimal`, `create_financial_entries`, `re`, `operations/routes.py`, `ERPAppTestCase`, `service.py`, `scheduling/routes.py`, `FinancialEntry`, `AssistantTest`, `business_reports.py`, `login_required`, `BusinessReadinessTest`, `management.py`, `get_system_settings`, `json`, `create_app`, `app/models.py`, `ReviewRegressionTest`, `app/services.py`, `app/__init__.py`, `datetime`?**
  _High betweenness centrality (0.079) - this node is a cross-community bridge._
- **Are the 97 inferred relationships involving `WorkOrder` (e.g. with `plate_history()` and `serialize_work_order()`) actually correct?**
  _`WorkOrder` has 97 INFERRED edges - model-reasoned connections that need verification._
- **Should `api.py` be split into smaller, more focused modules?**
  _Cohesion score 0.0551930876388644 - nodes in this community are weakly interconnected._
- **Why does `FinancialEntry` connect `FinancialEntry` to `api.py`, `test_structure.py`, `web.py`, `Client`, `fiscal.py`, `current_user`, `test_review_regressions.py`, `DataMigrationTest`, `parse_decimal`, `create_financial_entries`, `re`, `ERPAppTestCase`, `service.py`, `WorkOrder`, `business_reports.py`, `login_required`, `management.py`, `get_system_settings`, `json`, `app/models.py`, `BusinessReportsTest`, `ReviewRegressionTest`, `app/services.py`, `datetime`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Are the 42 inferred relationships involving `Client` (e.g. with `client_resource()` and `clients_collection()`) actually correct?**
  _`Client` has 42 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_structure.py` be split into smaller, more focused modules?**
  _Cohesion score 0.051061388410786 - nodes in this community are weakly interconnected._
- **Why does `14. Primeira fila de execução` connect `test_structure.py` to `scheduling/routes.py`, `Plano de estruturação e implementação — ERP Automotivo`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._