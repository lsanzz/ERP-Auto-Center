---
title: "Visual do ERP: painel com SVG, ícones inline e regras de CSS globais"
author: Lsanzz
date: 2026-10-20
branch: master
touches:
  - app/finance_overview.py
  - app/static/dashboard.css
  - app/static/dashboard.js
  - app/static/polish.css
  - app/templates/_icons.html
  - app/templates/base.html
  - app/templates/dashboard/overview.html
  - website/templates/features.html
  - website/templates/index.html
---

## Decided
- Gráficos do painel são SVG gerados no servidor (`dashboard_charts`/`area_path` em app/finance_overview.py), sem biblioteca JS; animações só com transform/opacity/stroke em app/static/dashboard.css.
- Ícones são SVG inline pelo macro `icon()` de app/templates/_icons.html (importado em base.html e no painel). Para um ícone novo, adicione o path no dicionário ICONS.
- app/static/polish.css é a camada global de acabamento (entrada das páginas, hover, ícones do menu) e respeita prefers-reduced-motion.
- Landing (website/templates/index.html, features.html) usa texto curto e simples para mecânicos; manter 3D, tour e demonstrações.

## Watch out
- `body :is(button,.button)` em design-system.css define position:relative e cores; elementos fixos ou coloridos precisam de seletor mais forte (ex.: `body button.ai-launcher`).
- `--primary` no tema do ERP é quase branco em alguns contextos; use `--color-primary` para azul.
- A animação global `page-in` do polish.css cobre .hub-panel/.hub-kpi; no painel a entrada escalonada usa `.dash .rise` para vencer a especificidade, senão os cartões ficam com opacity 0.
- O teste de login procura o texto "Seu dia na oficina" no painel.
