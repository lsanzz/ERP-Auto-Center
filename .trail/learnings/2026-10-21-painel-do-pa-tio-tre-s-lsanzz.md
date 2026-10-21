---
title: "Painel do pátio: três colunas arrastáveis e status da O.S."
author: Lsanzz
date: 2026-10-21
branch: master
touches:
  - app/scheduling/floor.py
  - app/scheduling/routes.py
  - app/scheduling/services.py
  - app/static/painel.css
  - app/static/painel.js
  - app/templates/agenda/painel.html
  - tests/test_scheduling.py
---

## Decided
- O Painel do pátio (/agenda/painel) mostra só três colunas: Aguardando (RECEPCAO, AGUARDANDO_APROVACAO, AGUARDANDO_PECA), Em andamento (DIAGNOSTICO, EM_EXECUCAO, CONTROLE_QUALIDADE) e Atendida (PRONTO). O mapa fica em FLOOR_COLUMNS (app/scheduling/services.py).
- Arrastar chama POST /agenda/patio/<id>/coluna -> move_to_column: Em andamento = EM_EXECUCAO/EM_ANDAMENTO; Atendida = PRONTO + status FINALIZADA (data_saida hoje); voltar para Aguardando = RECEPCAO + ABERTA e limpa data_saida. "Entregar" no cartão Atendida usa a rota antiga /etapa com ENTREGUE.
- Arrastar usa Pointer Events numa alça (touch-action:none), não HTML5 drag-and-drop, para funcionar no toque; rola a página perto das bordas no celular.
- Boxes, técnicos, estoque baixo e movimentações saíram do painel a pedido do usuário (menos informação). O quadro completo por etapa continua em /agenda/patio.

## Watch out
- base.html tem `.button, button {color: var(--color-canvas-white) !important}`; botões com cor própria (ex.: a alça .pk-grip) precisam de `!important` na cor, não só seletor mais forte.
- Mover para Atendida não lança contas a receber nem baixa estoque; isso continua pelo botão "Lançar contas" da O.S.
