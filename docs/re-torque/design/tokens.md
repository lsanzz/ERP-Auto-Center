# Design tokens do clone

Origem: `DESIGN.md` fornecido pelo usuário [doc SRC-003]. Os tokens visuais do template Torque **não** foram extraídos nem usados (template comercial, ver `00-charter.md`).

Implementação: `app/static/design-system.css` no erp-oficina.

| Token | Valor | Uso |
|---|---|---|
| `--color-canvas` | `#f5f5f5` | Fundo da página, inputs, botão secundário |
| `--color-paper` | `#ffffff` | Cards e popovers |
| `--color-surface-alt` | `#fafafa` | Navegação e card sutil |
| `--color-ink` | `#0a0a0a` | Texto principal e botão primário |
| `--color-ink-soft` | `#171717` | Badge sólido |
| `--color-mid-gray` | `#737373` | Texto secundário |
| `--color-hairline` | `#e5e5e5` | Bordas |
| `--color-ember` | `#e7000b` | Somente destrutivo e erro |
| Fonte | Geist, fallback Inter | Toda a interface |
| Raio | 18px interativos, 24px cards, 10px aninhados | |
| Sombra de card | hairline 1px + 1px 3px + 1px 2px -1px | |

Etapas do pátio: o sistema é monocromático, então as etapas se distinguem por peso de tom (badge sólido, suave ou contorno) e por um ponto de status em escala de cinza. Atraso usa `--color-ember`, porque é um estado de erro.
