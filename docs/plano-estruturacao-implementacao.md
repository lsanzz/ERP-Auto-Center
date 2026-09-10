# Plano de estruturação e implementação — ERP Automotivo

## Andamento — 06/09/2026

Implementação iniciada. Consulte [Entrega 01 — Base técnica e veículos](entrega-01-base-e-veiculos.md) para ativação, migração, testes e limitações.

- [x] Corrigir filtros de status, indicadores e funções duplicadas.
- [x] Introduzir CSRF, cookies e bloqueio de usuários inativos.
- [x] Disponibilizar baseline Alembic e transição do bootstrap legado.
- [x] Criar cadastro de veículos, histórico de proprietário e quilometragem.
- [x] Vincular veículos a orçamento/OS e exibir prontuário.
- [x] Importação simulada/idempotente de dados antigos com conflitos.
- [x] Auditoria automática, proteção de segredos em produção e rate limit persistente de login.
- [x] Garantias vinculadas às ordens de serviço.
- [x] Implementar primeira versão da agenda, recursos e quadro do pátio (fase 2).
- [x] Primeira versão de inspeção detalhada com fotos e aceite digital do orçamento (fases 3 e 4).
- [x] Reserva/consumo de peças, razão de estoque, vencidos e projeção financeira de 30 dias (fases 5 e 6).
- [ ] Completar recursos avançados das fases 3–8 e decidir se a fase 9 (SaaS/filiais) faz parte do produto.

As entregas possuem migrations MySQL e testes automatizados. Não houve implantação nem migração no banco de produção.

## 1. Objetivo do produto

Evoluir o ERP atual para uma plataforma de gestão integrada para oficinas, auto centers, centros automotivos, autoelétricas, funilarias, lojas de peças e operações com frotas.

O produto deve combinar a cobertura administrativa de um ERP geral — financeiro, estoque, fiscal, cadastros e relatórios — com uma operação automotiva profunda, centrada no veículo e na jornada:

`Agendamento → Recepção → Inspeção → Diagnóstico → Orçamento → Aprovação → Execução → Controle de qualidade → Faturamento → Entrega`

### Resultados esperados

- Eliminar recadastro entre orçamento, OS, estoque, financeiro e fiscal.
- Permitir saber, em tempo real, onde está cada veículo e o que impede sua entrega.
- Medir lucro por OS, produtividade, conversão de orçamentos e retorno de clientes.
- Criar uma experiência simples no computador, tablet e celular.
- Preparar a aplicação para integrações, filiais e futura oferta como SaaS.

## 2. Princípios de implementação

1. **Veículo como entidade central:** placa e descrição não devem continuar como simples textos repetidos.
2. **Uma operação gera os efeitos seguintes:** aprovar reserva peças; finalizar gera financeiro; faturar gera fiscal; entregar encerra a operação.
3. **Rastreabilidade:** estoque, caixa, aprovações e mudanças de status precisam de histórico, não apenas saldo atual.
4. **Automação com possibilidade de reversão:** toda automação financeira ou de estoque deve ter estorno seguro e auditável.
5. **Entrega incremental:** cada fase deve colocar uma melhoria utilizável em produção.
6. **Monólito modular primeiro:** manter Flask, mas separar domínios antes de considerar microsserviços.
7. **Segurança por padrão:** permissões, auditoria, proteção CSRF, segredos e backups entram antes da expansão comercial.

## 3. Diagnóstico da base atual

### Capacidades existentes a preservar

- Autenticação e perfis básicos.
- Clientes e funcionários.
- Produtos, serviços, fornecedores e entrada por XML.
- Orçamento com conversão para OS.
- OS com itens, checklist, pagamentos e histórico de status.
- Contas a pagar/receber e contas bancárias.
- NF-e/NFS-e e integração com provedor fiscal.
- PDF de OS, API JSON e relatórios iniciais.
- MySQL/InnoDB em produção e controle otimista em entidades críticas.

### Lacunas estruturais

- Não existe entidade persistente de veículo nem histórico de quilometragem.
- Não existem agenda, boxes/elevadores, capacidade, apontamento de horas ou Kanban operacional.
- Checklist é fixo e não aceita fotos, assinatura ou modelos configuráveis.
- Estoque é controlado principalmente pelo saldo do produto, sem razão de movimentos e reservas.
- Financeiro não possui plano de contas, centro de custo, conciliação ou DRE.
- Permissões são baseadas em poucos papéis, sem matriz granular.
- Alterações de schema são feitas por `db.create_all()` e `ALTER TABLE` manual.
- Não há camada uniforme de auditoria, armazenamento de anexos ou processamento assíncrono.
- A cobertura automatizada ainda é pequena para financeiro, fiscal e estoque.

## 4. Arquitetura-alvo

### 4.1 Organização do código

Manter um monólito Flask modular:

```text
app/
  common/          # autenticação, auditoria, arquivos, paginação, erros
  customers/       # clientes e contatos
  vehicles/        # veículos, odômetro e histórico
  scheduling/      # agenda, recursos e capacidade
  inspections/     # checklists, fotos, assinatura e laudos
  estimates/       # orçamentos, revisões e aprovações
  work_orders/     # OS, etapas, apontamentos e garantias
  inventory/       # produtos, locais, movimentos, reservas e compras
  finance/         # contas, caixa, DRE e conciliação
  fiscal/          # documentos e provedores fiscais
  reports/         # indicadores, exportações e consultas
  integrations/    # WhatsApp, pagamentos, bancos, placa e webhooks
```

Cada domínio deve conter rotas web/API, modelos, esquemas de entrada, serviços de negócio e testes. Regras críticas não devem ficar em templates ou diretamente nas rotas.

### 4.2 Componentes técnicos

- **Banco:** MySQL 8.4/InnoDB com `utf8mb4`.
- **Migrações:** Alembic/Flask-Migrate, com upgrade e downgrade testados.
- **Arquivos:** armazenamento compatível com S3 para fotos, PDFs e XML; filesystem apenas no desenvolvimento.
- **Tarefas assíncronas:** fila para mensagens, geração pesada de documentos, importações e consultas fiscais.
- **Cache/filas:** Redis quando as tarefas assíncronas forem introduzidas.
- **Observabilidade:** logs estruturados, identificação da requisição, captura de exceções e health checks.
- **API:** prefixo versionado `/api/v1`, paginação, validação, idempotência nas operações críticas e documentação OpenAPI.
- **Interface:** manter Jinja no curto prazo, adotando componentes reutilizáveis e JavaScript modular; PWA responsiva antes de considerar aplicativo nativo.

### 4.3 Preparação para multiempresa

No primeiro ciclo, o sistema pode continuar operando com uma empresa por instalação. Entretanto, novos domínios devem receber uma abstração de organização/filial:

- `Organization`: empresa/assinante.
- `Branch`: unidade física ou filial.
- `Membership`: usuário, organização, filial e papel.

A ativação real de multiempresa deve ocorrer somente depois de segurança, auditoria e testes de isolamento. Até lá, usar uma organização padrão, evitando espalhar regras de locatário pela aplicação.

## 5. Modelo de dados planejado

### 5.1 Clientes e veículos

**Vehicle**

- cliente atual, placa, chassi, Renavam;
- marca, modelo, versão, ano fabricação/modelo;
- motor, combustível, câmbio, cor e categoria;
- quilometragem atual e datas de atualização;
- situação ativa/inativa e observações.

**VehicleOwnershipHistory** registra trocas de proprietário.  
**OdometerReading** registra quilometragem, origem e usuário.  
**VehicleAttachment** registra fotos/documentos com tipo, hash e metadados.

Orçamento, agendamento e OS passam a referenciar `vehicle_id`, preservando campos de texto como snapshot histórico durante a migração.

### 5.2 Agenda e operação

**Appointment**: cliente, veículo, data, duração, serviço pretendido, responsável, origem e status.  
**WorkshopResource**: box, elevador, alinhador, técnico ou outro recurso.  
**ResourceAllocation**: reserva de recurso por período.  
**WorkOrderStageHistory**: etapa, início, fim, usuário, motivo de espera.  
**TimeEntry**: mecânico, serviço, início, fim, pausa e horas produtivas.

Estados oficiais da OS:

```text
ABERTA
EM_DIAGNOSTICO
AGUARDANDO_APROVACAO
AGUARDANDO_PECA
PROGRAMADA
EM_EXECUCAO
EM_CONTROLE_QUALIDADE
PRONTA
FINALIZADA
ENTREGUE
CANCELADA
```

O banco guarda códigos sem acento e a interface mostra rótulos traduzidos. Toda transição deve passar por um serviço que valide origem, destino e efeitos colaterais.

### 5.3 Inspeção

**InspectionTemplate** e **InspectionTemplateItem** definem modelos por ramo/tipo de veículo.  
**Inspection** representa entrada, diagnóstico, qualidade ou entrega.  
**InspectionAnswer** aceita conforme/não conforme/não aplicável, texto, número e observação.  
**InspectionMedia** liga fotos e vídeos às respostas.  
**Signature** registra assinatura, nome, data, IP e versão do documento.

### 5.4 Orçamento e aprovação

**EstimateRevision** preserva versões do orçamento.  
**EstimateApproval** registra decisão por item, total aprovado, identidade, data, IP e token utilizado.  
**CustomerPortalToken** cria links temporários, revogáveis e de uso limitado.

Itens precisam distinguir: recomendado, necessário, adicional, aprovado, recusado e adiado.

### 5.5 Estoque e compras

**StockLocation** representa estoque principal, balcão, filial, veículo de apoio ou quarentena.  
**StockMovement** é o razão imutável: entrada, saída, reserva, liberação, consumo, devolução, ajuste, transferência e estorno.  
**StockBalance** pode ser uma projeção/cache derivada dos movimentos.  
**StockReservation** liga produto, OS, local e quantidade.  
**PurchaseRequest**, **SupplierQuote**, **PurchaseOrder** e respectivos itens estruturam a reposição.  
**InventoryCount** e **InventoryCountItem** suportam inventário físico.

Regras:

- aprovação do orçamento pode reservar peças;
- início da execução confirma separação;
- finalização consome a reserva;
- cancelamento libera ou estorna;
- saldo negativo exige permissão explícita;
- nenhum movimento confirmado é apagado.

### 5.6 Financeiro

**ChartOfAccount**: plano de contas hierárquico.  
**CostCenter**: administração, oficina, peças, funilaria etc.  
**FinancialEntry** deve receber competência, emissão, vencimento, liquidação, conta contábil e centro de custo.  
**BankTransaction** guarda extrato importado/integrado.  
**BankReconciliation** associa transação bancária e lançamento.  
**CommissionRule** e **CommissionEntry** calculam comissão por serviço, peça, margem ou valor fixo.

A margem da OS deve considerar receita, custo registrado das peças, descontos, taxas, comissão e outros custos diretos. O custo precisa ser capturado como snapshot no momento do consumo.

### 5.7 Auditoria e comunicação

**AuditEvent**: usuário, ação, entidade, identificador, antes/depois, data, IP e correlação.  
**MessageTemplate**: canal, evento, texto e variáveis permitidas.  
**MessageDelivery**: destinatário, conteúdo, provedor, status, tentativas e erro.  
**WebhookSubscription/WebhookDelivery**: integrações externas com assinatura e retentativa.

## 6. Fluxos integrados principais

### Fluxo de atendimento

1. Recepcionista agenda cliente e veículo.
2. Na chegada, confirma dados, quilometragem e recursos.
3. Executa inspeção de entrada com fotos e assinatura.
4. Mecânico registra diagnóstico, peças e serviços.
5. Sistema gera revisão do orçamento e envia link ao cliente.
6. Aprovação registra cada item e reserva peças.
7. Líder aloca técnico, box e prazo.
8. Mecânico aponta horas e conclui tarefas.
9. Controle de qualidade executa checklist de saída.
10. Finalização consome estoque e gera contas a receber.
11. Emissão fiscal usa os dados da OS sem recadastro.
12. Entrega registra aceite e encerra a ordem.

### Fluxo de compra

1. Estoque mínimo, falta numa OS ou demanda manual cria solicitação.
2. Comprador coleta cotações e escolhe fornecedor.
3. Pedido aprovado gera previsão financeira.
4. XML/recebimento confere pedido, quantidade e custo.
5. Entrada gera movimentos de estoque e confirma conta a pagar.
6. Divergências ficam em fila de tratamento.

## 7. Plano de implementação por fases

As durações abaixo consideram uma pessoa desenvolvedora em dedicação principal. Servem para ordenar o trabalho, não como compromisso fechado de calendário.

### Fase 0 — Estabilização técnica (2 semanas)

**Entregas**

- Corrigir códigos divergentes de status nos relatórios.
- Separar “entradas de hoje” de “veículos atualmente no pátio” no painel.
- Remover funções duplicadas e consolidar constantes/enums.
- Introduzir Flask-Migrate/Alembic e gerar baseline do banco atual.
- Exigir `SECRET_KEY` segura em produção e proteger formulários com CSRF.
- Definir política para tokens fiscais e segredos.
- Criar testes de OS → estoque → financeiro → fiscal.
- Documentar backup, restauração e configuração por ambiente.

**Critério de saída:** build limpo, migração reproduzível e fluxo crítico coberto por testes.

### Fase 1 — Veículo e prontuário (2 a 3 semanas)

**Entregas**

- Criar `Vehicle`, histórico de proprietário e odômetro.
- Migrar placas/descrições existentes com deduplicação assistida.
- Vincular cliente, orçamento e OS ao veículo.
- Criar página do veículo com timeline de atendimentos.
- Registrar recomendações futuras e garantias.

**Critério de saída:** abrir o veículo e visualizar todo o seu histórico sem procurar OS individualmente.

### Fase 2 — Agenda, pátio e capacidade (3 semanas)

**Entregas**

- Agenda diária/semanal com agendamento rápido.
- Cadastro de boxes, elevadores e recursos.
- Conversão de agendamento em OS.
- Kanban da oficina com tempo em etapa e motivo de bloqueio.
- Previsão de entrega e alertas de atraso.
- Painéis específicos para recepção, mecânico e gestor.

**Critério de saída:** equipe consegue conduzir o dia pela agenda e pelo quadro, sem planilha paralela.

### Fase 3 — Inspeção digital e anexos (3 semanas)

**Entregas**

- Checklists configuráveis e versionados.
- Inspeções de entrada, diagnóstico, qualidade e saída.
- Upload otimizado de fotos pelo celular.
- Marcação de avarias, itens deixados e combustível.
- Assinatura e geração de laudo PDF.
- Política de retenção e acesso aos arquivos.

**Critério de saída:** recepção completa realizada em tablet/celular e laudo recuperável pela OS.

### Fase 4 — Orçamento e aprovação digital (3 semanas)

**Entregas**

- Revisões imutáveis do orçamento.
- Aprovação total, parcial, recusa e adiamento por item.
- Portal público seguro, responsivo e sem necessidade de cadastro.
- Evidências de aprovação e expiração/revogação de links.
- Envio por WhatsApp/e-mail através de adaptadores.
- Conversão apenas dos itens aprovados para a execução.

**Critério de saída:** cliente autoriza pelo celular e a oficina possui prova verificável da decisão.

### Fase 5 — Estoque rastreável e compras (4 semanas)

**Entregas**

- Locais, razão de movimentos e saldos derivados.
- Reserva, separação, consumo, liberação, devolução e estorno por OS.
- Inventário físico e ajuste autorizado.
- Alertas mínimo/máximo e curva ABC.
- Solicitação, cotação e pedido de compra.
- Conciliação de pedido com XML e recebimento.
- Relatório de giro, ruptura, custo e margem de peças.

**Critério de saída:** todo saldo pode ser explicado pela soma dos movimentos e rastreado até sua origem.

### Fase 6 — Financeiro gerencial (4 semanas)

**Entregas**

- Plano de contas e centros de custo.
- Regime de competência e caixa.
- Fluxo realizado/projetado e DRE.
- Importação de extratos e conciliação assistida.
- Taxas de cartão, juros, descontos e previsão de recebimento.
- Comissão configurável e fechamento por período.
- Margem e rentabilidade por OS, veículo, cliente, serviço e unidade.

**Critério de saída:** DRE reconcilia com os lançamentos e cada OS apresenta receita, custo e margem explicáveis.

### Fase 7 — Fiscal e integrações (3 semanas)

**Entregas**

- Estados fiscais padronizados e processamento assíncrono.
- Consulta, cancelamento, correção e tratamento de rejeições.
- Webhooks internos e externos com retentativa.
- API `/api/v1` documentada.
- Integrações de pagamento, contabilidade e comunicação.
- Monitoramento de indisponibilidade e fila de reprocessamento.

**Critério de saída:** falha externa não perde operação e pode ser reprocessada com segurança/idempotência.

### Fase 8 — Indicadores e experiência (3 semanas)

**Entregas**

- Garantia e identificação de retrabalho.
- Dashboard com conversão, ticket, margem, produtividade, prazo e retorno.
- Exportações PDF/Excel e filtros salvos.
- PWA instalável, responsiva e adequada a tablet.

**Critério de saída:** gestor acompanha os principais indicadores operacionais e de qualidade.

### Fase 9 — SaaS e filiais, se fizer parte do negócio (4 a 6 semanas)

**Entregas**

- Isolamento por organização e filial.
- Convites, memberships e matriz granular de permissões.
- Configuração fiscal e numeração por filial.
- Estoques, contas, relatórios consolidados e transferências entre filiais.
- Planos, limites, assinatura, onboarding e exportação dos dados.
- Testes automáticos contra vazamento entre empresas.

**Critério de saída:** nenhum acesso ou consulta consegue atravessar organizações e o ciclo de contratação/onboarding é auditável.

## 8. Roadmap sugerido

### Marco A — Operação automotiva profissional

Fases 0 a 4. Resultado: veículo, agenda, pátio, inspeção e aprovação digital funcionando de ponta a ponta.

### Marco B — ERP integrado

Fases 5 e 6. Resultado: estoque rastreável, compras, financeiro gerencial e margem real por OS.

### Marco C — Plataforma escalável

Fases 7 e 8. Resultado: fiscal resiliente, integrações, indicadores e boa experiência móvel.

### Marco D — Produto comercial multiempresa

Fase 9. Executar somente se houver estratégia de comercialização para várias empresas.

## 9. Backlog de indicadores

### Operação

- veículos no pátio e por etapa;
- OS atrasadas e tempo médio por etapa;
- ocupação de boxes/elevadores;
- horas disponíveis, apontadas e faturadas;
- produtividade e eficiência por técnico;
- prazo prometido versus realizado.

### Comercial

- orçamento emitido, aprovado, parcial e recusado;
- taxa e tempo médio de aprovação;
- ticket médio e itens adiados;
- clientes novos, recorrentes e inativos.

### Estoque

- itens abaixo do mínimo, ruptura e excesso;
- giro e cobertura em dias;
- divergência de inventário;
- peças reservadas, paradas e devolvidas;
- margem por produto/categoria.

### Financeiro

- contas vencidas e previsão de caixa;
- DRE mensal;
- receita, custo e margem por OS;
- faturamento de peças versus serviços;
- taxas financeiras e inadimplência;
- comissão provisionada e paga.

### Qualidade

- retorno em garantia/retrabalho;
- reclamações e satisfação;
- falhas por tipo de serviço;
- inspeções incompletas.

## 10. Segurança, LGPD e confiabilidade

- CSRF em todos os formulários mutáveis.
- Cookies `Secure`, `HttpOnly` e `SameSite` em produção.
- Rate limit em login, links públicos e consultas externas.
- Permissões por ação: visualizar custo, conceder desconto, movimentar estoque, liquidar, estornar, emitir/cancelar nota e exportar dados.
- Criptografia ou cofre de segredos para tokens fiscais e integrações.
- Auditoria de alterações sensíveis, inclusive antes/depois.
- URLs assinadas e temporárias para anexos.
- Validação de tipo, tamanho e conteúdo de uploads.
- Backup diário automatizado e teste periódico de restauração.
- Política de retenção, exportação e exclusão/anomização de dados pessoais.
- Dependências verificadas e atualizadas em rotina definida.

## 11. Estratégia de testes

### Pirâmide mínima

- **Unitários:** cálculos, estados, parcelas, comissões, margem e regras de estoque.
- **Integração:** banco, migrações, locks, importação XML, provedores e webhooks.
- **Fluxos ponta a ponta:** agendamento até entrega; compra até pagamento; cancelamento/estorno.
- **Contrato:** payloads da API e adaptadores externos.
- **Segurança:** papéis, CSRF, links expirados, uploads e isolamento por organização.

### Casos financeiros obrigatórios

- arredondamento e parcelamento;
- liquidação parcial/total;
- juros, descontos, taxas e acréscimos;
- estorno sem duplicar saldo;
- concorrência em finalização e baixa de estoque;
- cancelamento fiscal e operacional;
- mudança retroativa de custo/competência.

## 12. Estratégia de migração

1. Congelar e documentar o schema atual como baseline Alembic.
2. Criar novas tabelas sem remover campos existentes.
3. Migrar dados em lotes idempotentes, gerando relatório de conflitos.
4. Executar leitura compatível durante uma versão de transição.
5. Validar contagens, somas financeiras e saldos de estoque antes/depois.
6. Ativar novos fluxos por feature flags quando o risco justificar.
7. Remover campos antigos somente após uma versão estável e backup validado.

Para veículos, agrupar inicialmente por cliente + placa normalizada. Registros sem placa ou com conflito devem ir para revisão manual, nunca ser unidos automaticamente por descrição.

## 13. Padrão de entrega de cada história

Uma história só é concluída quando possui:

- regra de negócio implementada fora da rota/template;
- permissão definida;
- evento de auditoria quando aplicável;
- migração de banco revisada;
- validação e mensagens de erro claras;
- layout responsivo e estados vazio/carregando/erro;
- testes automatizados proporcionais ao risco;
- documentação da API/uso atualizada;
- telemetria/log útil para suporte;
- plano de estorno ou recuperação quando modifica dinheiro, estoque ou fiscal.

## 14. Primeira fila de execução

Ordem recomendada para iniciar imediatamente:

1. Corrigir filtro de status e métricas do painel.
2. Consolidar constantes/status e eliminar duplicações em `services.py`.
3. Implantar Alembic, CSRF, configuração segura e testes do fluxo crítico.
4. Desenhar e migrar `Vehicle` + `OdometerReading`.
5. Alterar cliente, orçamento e OS para selecionar veículo cadastrado.
6. Criar timeline do veículo.
7. Criar `Appointment`, recursos e agenda.
8. Criar histórico de etapas e quadro do pátio.
9. Generalizar checklist e armazenamento de anexos.
10. Implementar aprovação digital versionada.

## 15. Decisões que devem ser fechadas antes de cada marco

### Antes do Marco A

- Quais ramos entram no primeiro lançamento: oficina geral, auto center, motos, funilaria ou diesel?
- WhatsApp será manual via link ou integração oficial com envio automatizado?
- Fotos serão armazenadas localmente ou em serviço compatível com S3?
- Quais papéis reais existem na oficina?

### Antes do Marco B

- Método de custo: médio móvel ou custo por lote.
- Momento da reserva e do consumo de peças.
- DRE por competência, caixa ou ambos.
- Regras de comissão e responsabilidade por descontos.

### Antes do Marco D

- Instalação dedicada ou SaaS compartilhado.
- Modelo de planos e limites.
- Política de suporte, retenção e portabilidade.
- Requisitos fiscais e operacionais por filial.

---

Este plano prioriza primeiro o diferencial automotivo e a confiabilidade do núcleo. Recursos genéricos de ERP ou SaaS entram depois que a jornada completa do veículo estiver integrada e mensurável.
