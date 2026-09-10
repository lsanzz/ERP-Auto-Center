# Fiscal, financeiro e histórico — inventário de entrega

Referência funcional: páginas públicas da Ultracar, especialmente
https://ultracar.com.br/precos/, /fiscal/, /financeiro/ e /historico/.
Não houve acesso ao produto interno. Este documento não afirma paridade integral.

## Preservado no projeto

- Contas a pagar/receber, parcelamento, baixa, estorno e saldo bancário.
- Importação financeira/XML e dados de outros sistemas nos formatos já aceitos.
- Indicadores financeiros, DRE **gerencial simplificada**, custos por O.S. e conciliação CSV.
- Cadastro NCM/CFOP, NF-e de peças, NFS-e da O.S., devolução, consulta e cancelamento via integração existente.
- Histórico de veículos, auditoria e revisões de orçamento já existentes.

Esses recursos não foram reimplementados nem integralmente homologados nesta tarefa.

## Adicionado

| Recurso | Acesso | Comportamento |
| --- | --- | --- |
| Calendário de contas | Gestão → Calendário financeiro | Soma contas pendentes por dia e tipo; abre a lista filtrada para baixa |
| Balancete gerencial | Gestão → Balancete e fluxo | Filtro de período e conta, competência ou caixa, agrupamento e CSV |
| Fluxo realizado por período | Balancete → Caixa → Dia a dia | Líquido das baixas por data, acumulado do período (não saldo bancário) |
| Recibo | Financeiro → Pagas e recebidas → Recibo | Receita recebida; dados cadastrais da empresa, ajustes e impressão pelo navegador |
| Histórico central | Gestão → Histórico | Clientes, O.S., orçamentos, compras e notas por data de criação; atividades por usuário/entidade |
| Exportação de histórico | Histórico → Exportar CSV | Filtros aplicados; limite explícito de 10 mil registros; proteção contra fórmulas |
| Central fiscal | Gestão → Central fiscal | Pesquisa por número/chave/referência, tipo/status/período, consulta de status e XML |
| ID na auditoria de criação | Automático | Preenche ID após flush; rollback descarta o evento junto com a operação |

A auditoria mostra nomes de campos alterados, **não valores antigos/novos**. Eventos
antigos com ID ausente permanecem assim: não é possível reconstruí-los com certeza.
O recibo não é nota fiscal nem confirmação do banco. O balancete é gerencial, não
contábil de partidas dobradas. O CSV de histórico é relatório, não backup restaurável.

## Ainda não entregue / decisões necessárias

- Emissão de boletos: definir banco/provedor, contrato e mecanismo de retorno.
- NFC-e, nota conjugada, inutilização, busca de compras na SEFAZ e manifestação:
  implementar os fluxos e validar suporte/contratação no provedor fiscal e homologação.
  Nenhuma ação foi enviada à SEFAZ ou a um provedor nesta tarefa.
- SAT/MF-e e Sintegra: definir UF, cenário fiscal e aplicabilidade com responsável
  contábil antes da implementação; não presumir que a oferta comercial da referência
  representa uma obrigação ou uma solução válida para todas as empresas.
- DRE contábil completo, custeio/hora da oficina: falta definir classificações,
  encargos, horas produtivas e critérios. O cálculo simplificado existente foi preservado.
- Versionamento/restauração de todos os documentos, importador universal e backups
  em nuvem: não implementados; os importadores, revisões e scripts existentes não
  equivalem a essas funcionalidades completas.
- Layout livre do recibo e logo própria no recibo: não adicionados; o comprovante usa
  os dados cadastrados e mantém a assinatura LSHub.

## Design e validação

Referência dominante: sistema LSHub existente (`overview.css`, `lshub-ui.css`).
Metodologia Refero: build direto sobre design system, guia craft-details.

| Decisão | Referência / papel |
| --- | --- |
| Inter, Space Grotesk, fundo claro e azul de ação | Tokens existentes LSHub; sem nova identidade |
| Filtros GET e paginação | Guia Refero: estado na URL e listas limitadas |
| Tabelas com rolagem local | Padrão existente do financeiro; manter dados legíveis |
| Calendário sem biblioteca JS | Grade CSS, consultas agregadas e links nativos |
| Hover curto e reduced-motion | Padrão compartilhado LSHub |

Testes automatizados: `python -m pytest -q` — 61 passaram na primeira validação
integrada. Testes novos em `tests/test_business_reports.py`. Prévia visual isolada
em SQLite, sem dados reais. Não há alteração de esquema nesta entrega, portanto
não é necessária nova migração (pressupõe as migrações anteriores já aplicadas).

Para carregar templates novos em servidor sem reload, reinicie o Flask. Se necessário,
atualize a página com Ctrl+F5. Não é necessário recriar nem apagar o banco.
