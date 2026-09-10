# Direção da homepage — revisão monocromática

Referência principal: `C:/Users/lucas/OneDrive/Área de Trabalho/DESIGN.md`, fornecida
pelo proprietário, descrevendo a composição Calendly. O pedido explícito de preto
e branco prevalece sobre as instruções de azul/magenta/ciano contidas na referência.

## Alvo antes da implementação

Preservar: canvas claro, títulos geométricos grandes, espaço em branco,
cantos de 24px nos painéis e CTAs de 8px.
Adaptar: cores para branco, preto e cinzas neutros; sombras neutras; texto e conteúdo
para oficinas. Manter o formulário funcional e os contatos existentes.
Rejeitar: hero escuro anterior, acentos vermelhos, fotos, prints, simulações de
telas e provas sociais fictícias. Pedido atualizado do usuário: landing page sem
imagens demonstrativas. Usar abertura centralizada e seções textuais alternadas.

| Decisão | Fonte | Papel |
| --- | --- | --- |
| Fundo #f8f8f8, painéis brancos, texto #111 | Referência + pedido do usuário | Canvas e contraste |
| CTA preto com texto branco | Pedido do usuário | Ação principal |
| Hero de 68–80px, h2 de 38–50px | DESIGN.md | Hierarquia de leitura |
| Conteúdo sem imagens ou prints | Pedido atualizado do usuário | Composição tipográfica |
| Recursos em blocos textuais alternados | Layout de DESIGN.md adaptado | Ritmo em vez de grade repetitiva |
| Interações 120–200ms, entrada 320–400ms | Refero `references/motion.md` | Feedback, continuidade e hierarquia |
| Sem autoplay nas capturas | Refero motion | Controle de leitura pelo visitante |
| prefers-reduced-motion | Refero motion | Remover deslocamentos e animações opcionais |

## Validação

As três capturas realizadas antes da mudança de orientação foram retiradas dos
assets públicos e arquivadas em `instance/website/unused-captures/`.
Não existem imagens de demonstração ou galerias no HTML final.
Validar o resultado renderizado em desktop e celular, menu, seleção de plano,
perguntas frequentes, animações e formulário. O ERP não foi alterado.

Verificação realizada: desktop com 1146px e celular com 390px sem rolagem
horizontal; menu móvel abre e fecha ao navegar; CTA Profissional seleciona o
plano no formulário; nenhuma imagem no documento; nenhum erro de console;
seis testes do fluxo de contatos aprovados. A preferência de movimento reduzido
desativa animações e transições via CSS e impede o observador de entrada via JS.
