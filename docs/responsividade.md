# Responsividade do ERP

## Direção e referências

O alvo visual é o próprio LSHub (`lshub-ui.css` e o painel existente): fundos
claros, ações azuis, tipografia Inter/Space Grotesk e superfícies arredondadas.
A adaptação mantém as funções e permissões das telas no celular.

A pesquisa Refero não estava disponível (assinatura inativa). Foi utilizado o
guia `refero-design/references/craft-details.md`, em especial as seções de
formulários, toque, foco e contenção de rolagem, junto ao sistema visual existente.

| Decisão | Referência | Aplicação |
| --- | --- | --- |
| Preservar cores, fontes e superfícies | Design existente do LSHub | Reutilizar tokens; alterar distribuição e espaçamento conforme a largura |
| Menu expansível no celular | Navegação por grupos existente e pedido de acesso completo | Manter todos os links permitidos; permitir fechar com Escape e devolver foco |
| Campos em uma coluna | Guia de formulários e restrição de largura do celular | Evitar colunas estreitas; usar fonte de 16 px em campos e controles de toque de 44 px |
| Cartões nas listagens operacionais | Revisão da captura enviada pelo usuário | Manter todos os campos identificados e ações visíveis sem rolagem lateral; preservar tabelas no desktop |
| Rolagem nos relatórios e editores fiscais | Estrutura tabular existente | Indicar quando existem colunas fora da área visível |
| Diálogos limitados à área visível | Guia de toque e contenção de rolagem | Usar altura dinâmica, rolagem interna e bloquear a rolagem do fundo |

## Organização

- `app/static/responsive.css`: regras compartilhadas para navegação, formulários,
  botões, painéis, tabelas e diálogos. Carregado após os estilos existentes.
- `app/static/responsive.js`: expansão do menu e áreas de rolagem das tabelas,
  incluindo tabelas criadas dinamicamente. Tabelas com `data-mobile-cards` recebem
  rótulos derivados de seus cabeçalhos e cartões até 800 px. Seletores diretos
  preservam as tabelas internas de diálogos. A navegação continua disponível se o
  JavaScript estiver desativado.
- Estilos específicos dos módulos tratam editores, calendários, pátio e telas
  independentes. Não reduzir uma tabela apenas escondendo colunas com informações.

## Roteiro de validação

Verificar larguras de 320, 390, 768 e 1280 px com dados fictícios em banco de
testes isolado. Conferir ausência de rolagem horizontal na página, legibilidade,
menu aberto e fechado, perfil, filtros, formulários, inclusão dinâmica de itens,
rolagem de tabelas, abertura e fechamento de diálogos. Manter impressão legível.

Os testes de aplicação continuam com `python -m pytest`; a análise Python com
`python -m ruff check app tests`. A inspeção de responsividade requer navegador.

## Validação realizada

- 51 páginas em quatro larguras: 320, 390, 768 e 1280 px (204 verificações),
  com Edge/Chromium automatizado e banco SQLite temporário em memória.
- Nenhuma rolagem horizontal do documento e nenhum erro JavaScript nessa rodada.
- Interações verificadas: menu por toque, Escape e retorno do foco, perfil,
  diálogo de conta bancária, inclusão e remoção de itens da O.S., cálculo de
  valores, inclusão de pagamentos, ações da listagem e abas de configurações.
- Após o relato de opções inacessíveis na O.S., nove listagens com registros
  foram verificadas em 320, 390 e 768 px: todos os campos dentro da largura,
  menus acessíveis sem rolagem lateral e 18 verificações de controles de menu
  sem sobreposição. O diálogo de alteração de status também foi aberto e fechado.
  Em 1280 px, a apresentação tabular foi preservada.
- Inspeção visual de capturas do menu, painel, formulários e diálogo no celular.
- 104 testes Python aprovados; Ruff e verificação de sintaxe do JavaScript sem erros.

As chamadas a serviços externos foram bloqueadas na validação visual. O CAPTCHA
mantém a validação existente e utiliza apresentação compacta para caber nas telas
pequenas. A validação não substitui um teste em aparelho físico com Safari/iOS.
