# Revisão do sistema — 16/09/2026

Revisão local sobre o estado de trabalho existente, preservando as alterações anteriores de migração, financeiro e responsividade. Nenhuma implantação nem migração em banco real foi executada.

## Correções

| Área | Falha encontrada | Correção |
| --- | --- | --- |
| Financeiro | Repetir uma liquidação alterava novamente o saldo | Liquidação idempotente, com atualização bloqueada do lançamento no MySQL |
| Financeiro | Reconfirmar recebimento da OS podia trocar a conta histórica e estornar o banco errado | Preservação da conta e dos valores da liquidação original |
| Financeiro | Valores negativos, infinitos e texto inválido podiam chegar ao cálculo | Validação dos componentes e do líquido; rollback e mensagem no formulário |
| Financeiro | Conta inexistente ou inativa aceita na seleção da liquidação | Rejeição antes de concluir a baixa |
| API | JSON em formato de lista, texto ou escalar causava falhas internas | Resposta 400 para corpo que não seja objeto JSON |
| Permissões | Mecânico podia alterar clientes e orçamentos | Aplicação das capacidades existentes nas mutações web/API |
| Inspeção | Alteração de inspeções liberada a qualquer usuário autenticado | Capacidade `inspections.manage` para editar/anexar e `work_orders.view` para fotos |
| Fotos | Normalização EXIF podia perder o formato da imagem | Captura do formato antes da transformação; teste verifica persistência real da foto |
| Busca | Nomes e termos inseridos como HTML | Nós de texto seguros no histórico, autocomplete e itens da OS |
| Busca | Expressão regular construída com texto livre | Destaque por posição literal, aceitando colchetes e outros caracteres |
| Busca | Histórico inválido ou armazenamento bloqueado quebrava JavaScript | Leitura validada e degradação sem armazenamento |
| Interface | Cálculo do modal dependia de todos os campos existirem | Campos opcionais, conversão decimal e cálculo inicial |
| Acessibilidade | Sem atalho ao conteúdo e foco pouco visível | Link de salto, destino de foco, contorno mais forte e mensagens com papel acessível |
| Cache | Documentos e respostas privadas podiam permanecer em cache | `Cache-Control: no-store, private` para respostas dinâmicas |
| Segredos | Chave da CNPJá estava gravada no código e no histórico Git | Remoção do código; leitura opcional por `CNPJA_API_KEY`; rotação da chave antiga é obrigatória |
| Dependências | Flask 3.1.0 e Werkzeug 3.1.3 tinham vulnerabilidades publicadas | Atualização para Flask 3.1.3 e Werkzeug 3.1.6; `pip-audit` sem achados |
| XML | NF-e era processada pelo parser XML padrão | Uso de `defusedxml` e regressão com expansão de entidades maliciosa |
| Autorização | Listagem de clientes era pública e várias leituras/mutações ignoravam as capacidades por função | Autenticação na listagem e permissões uniformes em clientes, orçamentos, veículos, agenda, O.S., estoque e API |
| Sessão | Logout preservava estado de MFA e redirecionamento pós-login aceitava caminhos ambíguos | Limpeza integral da sessão e validação de destino local sem barras invertidas, esquema ou host |
| Senhas | Usuários comuns podiam receber senhas de seis caracteres e a carga inicial usava credenciais conhecidas | Mínimo de 12 caracteres e `INITIAL_ADMIN_PASSWORD` obrigatório fora de testes |
| Perfis | A tela aceitava só administrador/mecânico e convertia outros perfis silenciosamente | Suporte validado aos cinco perfis definidos pelo modelo de autorização |
| Landing | Debug direto, chave efêmera em produção e ausência de cabeçalhos defensivos | Debug opt-in apenas em desenvolvimento, segredo persistente obrigatório e CSP/HSTS/cabeçalhos defensivos |
| Integrações | URLs configuráveis aceitavam esquemas não seguros | Validação HTTPS sem credenciais embutidas para APIs fiscal e de placas |

## Direção visual e referências

Alvo: sistema visual LSHub já existente em `theme.css`, `lshub-ui.css` e `base.html`. Preservar superfícies claras, azul de ação, fontes existentes, densidade operacional e comportamento responsivo. Sem introduzir imagens decorativas ou outra identidade.

| Decisão | Referência | Aplicação |
| --- | --- | --- |
| Preservar paleta e composição | Design system existente do produto | Ajustes pontuais, mantendo o painel e o financeiro |
| Foco visível e salto ao conteúdo | Refero Design, `references/craft-details.md`, seções Focus States e Accessibility | Contorno com token de ação e navegação por teclado |
| Mensagens compreensíveis e cálculo inicial | Mesmo guia, Forms e Async Updates | Validação de liquidação e anúncio de mensagens |
| Modal contido e legível no celular | Mesmo guia, Touch & Mobile, mais `responsive.css` existente | Validação renderizada em viewport de 390 × 844 |

## Validação

- Suíte original: 109 testes aprovados, cobertura inicial de 56,29%.
- Resultado anterior: **170 testes aprovados**, cobertura **58,22%**. A revisão de segurança posterior ampliou novamente a suíte; consulte o resultado do último `pytest -q` no relatório de entrega.
- Novos testes em `tests/test_review_regressions.py`: valores inválidos, repetição da liquidação, histórico de banco/estorno, permissões, fotos, JSON, cache e abertura de 33 telas sem dados.
- Ruff e `git diff --check` sem erros na revisão.
- Bandit sem achados e `pip-audit` sem vulnerabilidades conhecidas nos manifestos do ERP e da landing.
- Prévia isolada com SQLite em memória e registros demonstrativos, sem conexão ao banco real.
- Navegador: painel desktop; financeiro e modal no celular; atualização de R$ 250,00 para R$ 275,00; menu abre e fecha com Escape; texto `<b>teste[</b>` exibido literalmente, sem elemento HTML injetado; sem overflow horizontal na tela financeira e sem erros de console observados.

## Limites e próximos investimentos

Os testes locais usam SQLite. Os locks de concorrência adicionados para MySQL precisam também ser exercitados em uma instância MySQL de homologação, especialmente duas liquidações simultâneas. O fluxo de migrations existente foi exercitado pela suíte local; a compatibilidade real com MySQL continua dependendo do job de CI próprio do projeto.

Integrações fiscais, CAPTCHA e consultas externas não foram acionadas com credenciais reais. A validação não substitui homologação fiscal nem representa uma auditoria completa de segurança. Convém ampliar gradualmente a cobertura de combinações de permissões e transições das ordens de serviço e extrair regras de negócio do módulo `web.py`, que concentra muitos fluxos.
