# Graph Report - erp-auto-center  (2026-10-22)

## Corpus Check
- 219 files · ~162,932 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 56 file(s) not represented in the graph (top: .css 21, .woff2 12, (none) 9)

## Summary
- 2053 nodes · 6686 edges · 177 communities (103 shown, 74 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 695 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `bd9d714e`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- as_json
- tools.py
- login_required
- app/models.py
- fiscal.py
- current_user
- test_review_regressions.py
- DataMigrationTest
- WorkOrder
- create_financial_entries
- re
- FinancialEntry
- operations/routes.py
- ERPAppTestCase
- service.py
- finance_overview.py
- data_migration/routes.py
- uninfe_connector.py
- scheduling/routes.py
- UniNFePreparationTests
- Product
- app.py
- system_admin.py
- AssistantTest
- llm.py
- issue
- uninfe_relay.py
- uninfe_xml.py
- web.py
- pdfs.py
- readers.py
- get_config
- hook.cjs
- apply_protocol
- uninfe_events.py
- UniNFeXmlTests
- business_reports.py
- Vehicle
- create_app
- site.js
- os
- replace_finance_exports.py
- S-000 {{screen_name}}
- test_uninfe_migrations.py
- flask
- marketing.py
- sqlalchemy
- backfill_categories.py
- Entrega 01 — Base técnica e cadastro de veículos
- Migração de dados
- BusinessReportsTest
- Integração UniNFe — estado de implementação
- Plano de estruturação e implementação — ERP Automotivo
- 7. Plano de implementação por fases
- Clone requirements: Torque
- UniNFeSubmission
- api.py
- C-000 {{neutral_name}}
- create_app
- alembic
- os
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
- test_landing_form.py
- API
- Entrega 02 — MySQL, agenda e pátio
- 8. Roadmap sugerido
- Implications for the clone
- vehicles.py
- Direção da homepage — revisão monocromática
- 15. Decisões que devem ser fechadas antes de cada marco
- 4. Arquitetura-alvo
- Production barriers: Torque
- Findings
- Torque: reverse engineering knowledge base
- SessionClient
- 20260906_03_operations.py
- 20260907_05_company_profile.py
- cep.js
- 11. Estratégia de testes
- 3. Diagnóstico da base atual
- Rules: {{area}}
- Topic: hidden writes
- json
- parse_decimal
- StructureTest
- 20260907_07_system_admin.py
- 20260909_08_management_foundation.py
- 20260922_11_uninfe.py
- 20260922_12_uninfe_submissions.py
- parse_date
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
- get_system_settings
- comercial/README.md
- Política de Privacidade — LS Hub (sistema)
- Employee
- FiscalApiConfig
- Implantação de uma oficina nova
- BusinessReadinessTest
- Cobrança das oficinas
- Homologação fiscal (NF-e de peças e NFS-e de serviços)
- Suporte ao cliente — Anexo III
- Links
- dashboard
- handle_stale_data
- backfill
- secrets
- .test_csrf_required_and_every_rendered_form_has_token
- budgets_add_item
- landing_context
- 20260914_10_data_migration.py
- 20260922_13_uninfe_dispatch.py
- 20260923_14_uninfe_cancel.py

## God Nodes (most connected - your core abstractions)
1. `WorkOrder` - 171 edges
2. `login_required()` - 129 edges
3. `Client` - 98 edges
4. `post()` - 92 edges
5. `FinancialEntry` - 89 edges
6. `current_user()` - 78 edges
7. `create_app()` - 76 edges
8. `permission_required()` - 73 edges
9. `parse_decimal()` - 67 edges
10. `DataMigrationTest` - 66 edges

## Surprising Connections (you probably didn't know these)
- `Fase 1 — Veículo e prontuário (2 a 3 semanas)` --references--> `Vehicle`  [INFERRED]
  docs/plano-estruturacao-implementacao.md → app/fleet/models.py
- `Site comercial LS Hub` --references--> `create_app()`  [INFERRED]
  docs/site-comercial.md → app/__init__.py
- `14. Primeira fila de execução` --references--> `Vehicle`  [INFERRED]
  docs/plano-estruturacao-implementacao.md → app/fleet/models.py
- `14. Primeira fila de execução` --references--> `OdometerReading`  [INFERRED]
  docs/plano-estruturacao-implementacao.md → app/fleet/models.py
- `Integração UniNFe — estado de implementação` --references--> `ManagedCompany`  [INFERRED]
  docs/integracao-uninfe.md → app/models.py

## Import Cycles
- None detected.

## Communities (177 total, 74 thin omitted)

### Community 0 - "as_json"
Cohesion: 0.15
Nodes (24): wrapped(), api_roles_required(), decorator(), wrapped(), as_json(), bank_account_resource(), bank_accounts_collection(), clients_collection() (+16 more)

### Community 1 - "tools.py"
Cohesion: 0.12
Nodes (21): _alternatives(), buscar_catalogo(), buscar_cliente(), buscar_veiculo_por_placa(), _catalog_match(), consultar_os(), contas_vencendo(), edit_draft_items() (+13 more)

### Community 2 - "login_required"
Cohesion: 0.10
Nodes (52): login_required(), get_fiscal_config(), bank_accounts_delete(), bank_accounts_edit(), bank_accounts_new(), budgets_delete(), budgets_edit(), clients_delete() (+44 more)

### Community 3 - "app/models.py"
Cohesion: 0.13
Nodes (10): register_database_commands(), seed_command(), ChartOfAccount, Client, CostCenter, Service, StockLocation, SystemSettings (+2 more)

### Community 4 - "fiscal.py"
Cohesion: 0.13
Nodes (22): cell(), build_focus_nfe_payload(), build_focus_nfse_payload(), build_internal_xml(), row(), build_work_order_invoice_payload(), decode_payload(), _digits() (+14 more)

### Community 5 - "current_user"
Cohesion: 0.08
Nodes (41): current_user(), has_permission(), wrapped(), login_user(), permission_required(), decorator(), wrapped(), role_required() (+33 more)

### Community 6 - "test_review_regressions.py"
Cohesion: 0.06
Nodes (29): _persistent_secret_key(), configure_observability(), JsonFormatter, InspectionPhoto, next_number(), NumberingTest, application(), browser_for() (+21 more)

### Community 7 - "DataMigrationTest"
Cohesion: 0.10
Nodes (5): configure_worker(), MigrationWorker, run_next_job(), PaymentMethod, DataMigrationTest

### Community 8 - "WorkOrder"
Cohesion: 0.10
Nodes (31): create_work_order_from_payload(), cancel(), confirm(), _friendly_error(), message(), new_conversation(), _pop_draft(), _rate_limited() (+23 more)

### Community 9 - "create_financial_entries"
Cohesion: 0.08
Nodes (4): create_financial_entries(), FinanceStockFlowsTest, ReviewRegressionTest, VhsysParityTest

### Community 10 - "re"
Cohesion: 0.16
Nodes (23): money(), parse_finance_export(), source_date(), normalize(), work_order_status(), key(), main(), source() (+15 more)

### Community 11 - "FinancialEntry"
Cohesion: 0.14
Nodes (20): FinancialEntry, WorkOrderChecklist, WorkOrderItem, add_work_order_item(), create_work_order_from_budget(), daily_cash_summary(), dashboard_data(), ensure_work_order_checklist() (+12 more)

### Community 12 - "operations/routes.py"
Cohesion: 0.12
Nodes (37): OdometerReading, VehicleOwnershipHistory, Budget, CommissionRule, CompanyPartner, InventoryCount, InventoryCountItem, SerializableMixin (+29 more)

### Community 13 - "ERPAppTestCase"
Cohesion: 0.07
Nodes (6): configure_security(), decrypt_secret(), encrypt_secret(), _fernet(), verify_totp(), ERPAppTestCase

### Community 14 - "service.py"
Cohesion: 0.12
Nodes (24): complete_orders(), item_key(), read_detailed_orders(), reconcile_os_payments(), candidate_client_names(), convert(), DefusedXmlException, digest_for() (+16 more)

### Community 15 - "finance_overview.py"
Cohesion: 0.15
Nodes (11): area_path(), dashboard_charts(), financial_overview(), home_context(), render_finance(), entry_party(), imported_details(), BankReconciliation (+3 more)

### Community 16 - "data_migration/routes.py"
Cohesion: 0.17
Nodes (21): DataMigration, MigrationRow, detail(), get_migration(), index(), private_response(), report(), generate() (+13 more)

### Community 17 - "uninfe_connector.py"
Cohesion: 0.27
Nodes (4): Client, main(), poll(), process_task()

### Community 18 - "scheduling/routes.py"
Cohesion: 0.09
Nodes (29): build_floor(), _card(), _elapsed(), Appointment, WorkOrderStageHistory, WorkshopResource, edit(), _form() (+21 more)

### Community 20 - "Product"
Cohesion: 0.13
Nodes (18): bank_import(), create_replenishment_request(), dre_section(), import_bank_csv(), index(), management_summary(), order_profitability(), receive_purchase() (+10 more)

### Community 21 - "app.py"
Cohesion: 0.15
Nodes (15): csrf_error(), demonstration(), _env_list(), favicon(), features(), _first_form_value(), _form_options(), health() (+7 more)

### Community 22 - "system_admin.py"
Cohesion: 0.19
Nodes (12): grace_ends(), subscription_status(), change_password(), current_system_admin(), dashboard(), integration(), login(), logout() (+4 more)

### Community 23 - "AssistantTest"
Cohesion: 0.14
Nodes (3): AssistantTest, propose(), FakeCompletions

### Community 24 - "llm.py"
Cohesion: 0.16
Nodes (9): AssistantUnavailable, _context(), enabled(), make_client(), run_turn(), spoken_plate(), inject_assistant(), listar_formas_pagamento() (+1 more)

### Community 26 - "uninfe_relay.py"
Cohesion: 0.19
Nodes (12): UniNFeRelayTask, authenticate(), credentials(), enqueue_invoice(), get_task(), list_tasks(), private_response(), problem() (+4 more)

### Community 27 - "uninfe_xml.py"
Cohesion: 0.24
Nodes (11): validate_unsigned(), add(), address(), allocate(), build_invoice(), contribution(), decimal(), digits() (+3 more)

### Community 28 - "web.py"
Cohesion: 0.09
Nodes (40): logout_user(), render_fiscal_center(), XmlInvoiceImport, client_history(), format_currency(), budgets_approve(), budgets_convert(), budgets_index() (+32 more)

### Community 29 - "pdfs.py"
Cohesion: 0.20
Nodes (7): generate_work_order_pdf(), _items_table(), _label_value(), _money(), _p(), _safe(), _section()

### Community 30 - "readers.py"
Cohesion: 0.13
Nodes (8): detect_html_table(), raw_rows(), read_table(), TableReader, TableStats, text_cell(), prepare(), _prepare()

### Community 31 - "get_config"
Cohesion: 0.23
Nodes (3): get_config(), reconcile_company_config(), UniNFeConfigTests

### Community 32 - "hook.cjs"
Cohesion: 0.17
Nodes (11): best(), entry(), fromPkg(), globalRoot(), newer(), onPath(), pkgAbove(), PKGS (+3 more)

### Community 33 - "apply_protocol"
Cohesion: 0.23
Nodes (5): apply_protocol(), collect_return(), document(), response(), UniNFeTransportTests

### Community 34 - "uninfe_events.py"
Cohesion: 0.22
Nodes (12): apply_cancellation_response(), build_cancellation(), cancel(), cancellation_prefix(), collect_cancellation(), _directory(), _key(), publish_file() (+4 more)

### Community 36 - "business_reports.py"
Cohesion: 0.16
Nodes (9): balance(), csv_download(), finance_calendar(), history(), net_expression(), period(), receipt(), report_data() (+1 more)

### Community 37 - "Vehicle"
Cohesion: 0.22
Nodes (12): Vehicle, edit(), _form(), index(), lookup(), new(), show(), toggle_active() (+4 more)

### Community 38 - "create_app"
Cohesion: 0.21
Nodes (8): create_app(), connect(), demonstration(), export_leads(), home_response(), index(), tokens(), unavailable_storage()

### Community 39 - "site.js"
Cohesion: 0.15
Nodes (14): clamp(), errorSummary, form, header, menu, navigation, onScroll(), revealables (+6 more)

### Community 40 - "os"
Cohesion: 0.20
Nodes (12): digits(), focus_request(), management_token(), NoRedirect, _parse_focus_datetime(), refresh_managed_companies(), sync_company(), ManagedCompany (+4 more)

### Community 41 - "replace_finance_exports.py"
Cohesion: 0.19
Nodes (6): MigrationKey, entry_description(), work_order_receivable_description(), main(), main(), main()

### Community 42 - "S-000 {{screen_name}}"
Cohesion: 0.14
Nodes (13): Anatomy, Data shown, Entry points, Interactions, Keyboard and accessibility, Microcopy, Not tested, Purpose (+5 more)

### Community 43 - "test_uninfe_migrations.py"
Cohesion: 0.19
Nodes (3): upgrade(), migrations(), UniNFeMigrationTests

### Community 46 - "sqlalchemy"
Cohesion: 0.17
Nodes (6): downgrade(), upgrade(), upgrade(), downgrade(), upgrade(), upgrade()

### Community 47 - "backfill_categories.py"
Cohesion: 0.17
Nodes (3): default_category(), _fill_category(), backfill()

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
Cohesion: 0.17
Nodes (12): 10. Segurança, LGPD e confiabilidade, 12. Estratégia de migração, 13. Padrão de entrega de cada história, 14. Primeira fila de execução, 1. Objetivo do produto, 2. Princípios de implementação, 6. Fluxos integrados principais, Andamento — 06/09/2026 (+4 more)

### Community 53 - "7. Plano de implementação por fases"
Cohesion: 0.18
Nodes (11): 7. Plano de implementação por fases, Fase 0 — Estabilização técnica (2 semanas), Fase 1 — Veículo e prontuário (2 a 3 semanas), Fase 2 — Agenda, pátio e capacidade (3 semanas), Fase 3 — Inspeção digital e anexos (3 semanas), Fase 4 — Orçamento e aprovação digital (3 semanas), Fase 5 — Estoque rastreável e compras (4 semanas), Fase 6 — Financeiro gerencial (4 semanas) (+3 more)

### Community 54 - "Clone requirements: Torque"
Cohesion: 0.20
Nodes (9): Build order, Clone requirements: Torque, Core loop, Data model, Launch blockers, Non-goals, Open questions, Problem and users (+1 more)

### Community 55 - "UniNFeSubmission"
Cohesion: 0.16
Nodes (7): UniNFeSubmission, consult(), issue(), access_key(), prepare(), UniNFeDispatchTests, UniNFeStorageTests

### Community 56 - "api.py"
Cohesion: 0.19
Nodes (25): api_login_required(), budget_add_item(), budget_approve(), budget_convert(), budget_resource(), budgets_collection(), client_resource(), _collect_work_order_item_payloads() (+17 more)

### Community 57 - "C-000 {{neutral_name}}"
Cohesion: 0.22
Nodes (8): Anatomy, Behavior, C-000 {{neutral_name}}, Keyboard and accessibility, Measurements and tokens, Not tested, States, Variants

### Community 58 - "create_app"
Cohesion: 0.07
Nodes (14): configure_upload_limit(), upgrade_legacy_vehicle_links(), create_app(), _date_br(), _datetime_br(), _normalize_database_url(), _run_schema_updates(), User (+6 more)

### Community 59 - "alembic"
Cohesion: 0.20
Nodes (3): upgrade(), upgrade(), upgrade()

### Community 60 - "os"
Cohesion: 0.20
Nodes (14): client_lookup_document(), _save_client_from_payload(), lookup_cep(), _best_address(), _build_address(), _build_cpfhub_address(), _first_value(), is_cnpj() (+6 more)

### Community 61 - "Operação em produção"
Cohesion: 0.25
Nodes (7): Backup e restauração, Implantação, Monitoramento, Operação em produção, Processos, Recuperação, Variáveis desta revisão (22/10/2026)

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

### Community 81 - "test_landing_form.py"
Cohesion: 0.12
Nodes (9): browser(), page_token(), test_form_has_options_even_without_env(), test_incomplete_request_is_rejected(), test_valid_request_is_saved_with_every_field(), grid(), ReloadVhsysTest, no_configured_key() (+1 more)

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

### Community 87 - "vehicles.py"
Cohesion: 0.15
Nodes (10): lookup_placa(), plate_history(), LocalSchemas, unsigned_schema(), _best_fipe(), _first_value(), lookup_plate(), normalize_plate_payload() (+2 more)

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
Cohesion: 0.25
Nodes (15): _cancel_focus_document(), cancel_focus_nfe(), cancel_focus_nfse(), _consult_focus_document(), consult_focus_nfe(), consult_focus_nfse(), create_or_update_fiscal_document(), create_parts_fiscal_document() (+7 more)

### Community 103 - "parse_decimal"
Cohesion: 0.20
Nodes (14): register_inventory_change(), _build_item_values(), _resolve_catalog_item(), _resolve_catalog_item_by_description(), split_installments(), parse_decimal(), _deep_text(), _format_cnpj_cpf() (+6 more)

### Community 109 - "parse_date"
Cohesion: 0.18
Nodes (9): add_months(), default_bank_account_id(), ensure_work_order_receivables(), method_account_map(), _plain(), update_subscription(), parse_date(), work_orders_index() (+1 more)

### Community 155 - "Contrato de Licença de Uso de Software (SaaS) — LS Hub"
Cohesion: 0.17
Nodes (12): 10. Limitação de responsabilidade, 11. Disposições gerais, 1. Objeto, 2. Implantação, 3. Preço, pagamento e reajuste, 4. Atraso e suspensão, 5. Nível de serviço (SLA), 6. Obrigações da LS HUB (+4 more)

### Community 156 - "get_system_settings"
Cohesion: 0.22
Nodes (9): budget_default_date(), get_system_settings(), budgets_new(), enforce_subscription(), _fill_budget_from_form(), _settings_positive_int(), _settings_prefix(), settings_save_operation() (+1 more)

### Community 157 - "comercial/README.md"
Cohesion: 0.29
Nodes (3): Acordo de Tratamento de Dados Pessoais (DPA) — Anexo II, Pacote comercial do LS Hub, Termos de Uso — LS Hub

### Community 158 - "Política de Privacidade — LS Hub (sistema)"
Cohesion: 0.20
Nodes (10): 1. Papéis, 2. Que dados tratamos e por quê, 3. Com quem compartilhamos, 4. Transferência internacional, 5. Por quanto tempo guardamos, 6. Segurança, 7. Direitos dos titulares, 8. Incidentes (+2 more)

### Community 159 - "Employee"
Cohesion: 0.28
Nodes (7): Employee, _back_to_list_or(), employees_edit(), employees_new(), _fill_employee_from_form(), work_orders_change_employee(), work_orders_change_status()

### Community 160 - "FiscalApiConfig"
Cohesion: 0.54
Nodes (6): _focus_base_url(), _focus_url(), import_nfe_xml_to_focus(), save_fiscal_config_from_form(), FiscalApiConfig, save_config()

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

### Community 167 - "dashboard"
Cohesion: 0.50
Nodes (3): client_lookup_cnpj(), dashboard(), health()

### Community 172 - "budgets_add_item"
Cohesion: 0.67
Nodes (3): budgets_add_item(), _resolve_item_payload(), work_orders_add_item()

## Knowledge Gaps
- **74 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `WorkOrder` connect `WorkOrder` to `as_json`, `tools.py`, `login_required`, `app/models.py`, `fiscal.py`, `current_user`, `test_review_regressions.py`, `DataMigrationTest`, `create_financial_entries`, `re`, `FinancialEntry`, `operations/routes.py`, `ERPAppTestCase`, `service.py`, `finance_overview.py`, `scheduling/routes.py`, `Product`, `AssistantTest`, `web.py`, `get_system_settings`, `Employee`, `BusinessReadinessTest`, `business_reports.py`, `Vehicle`, `replace_finance_exports.py`, `budgets_add_item`, `api.py`, `create_app`, `vehicles.py`, `json`, `StructureTest`, `parse_date`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Are the 97 inferred relationships involving `WorkOrder` (e.g. with `plate_history()` and `serialize_work_order()`) actually correct?**
  _`WorkOrder` has 97 INFERRED edges - model-reasoned connections that need verification._
- **Should `tools.py` be split into smaller, more focused modules?**
  _Cohesion score 0.12413793103448276 - nodes in this community are weakly interconnected._
- **Why does `14. Primeira fila de execução` connect `Plano de estruturação e implementação — ERP Automotivo` to `scheduling/routes.py`, `operations/routes.py`, `Vehicle`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Are the 42 inferred relationships involving `Client` (e.g. with `client_resource()` and `clients_collection()`) actually correct?**
  _`Client` has 42 INFERRED edges - model-reasoned connections that need verification._
- **Should `login_required` be split into smaller, more focused modules?**
  _Cohesion score 0.1013277428371768 - nodes in this community are weakly interconnected._
- **Why does `Plano de estruturação e implementação — ERP Automotivo` connect `Plano de estruturação e implementação — ERP Automotivo` to `11. Estratégia de testes`, `3. Diagnóstico da base atual`, `9. Backlog de indicadores`, `Entrega 01 — Base técnica e cadastro de veículos`, `8. Roadmap sugerido`, `7. Plano de implementação por fases`, `15. Decisões que devem ser fechadas antes de cada marco`, `4. Arquitetura-alvo`, `5. Modelo de dados planejado`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._