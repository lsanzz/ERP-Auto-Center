---
title: Relatório por seção e Central fiscal
author: Lsanzz
date: 2026-10-21
branch: master
touches:
  - app/management.py
  - app/templates/gestao/index.html
  - app/templates/fiscal/center.html
  - app/security.py
---

Cada grupo do menu tem 'Relatório' como último item: Atendimento -> web.reports_index (O.S.); Estoque -> /gestao/?secao=estoque (peças no mínimo, movimentações, reposição); Gestão/Financeiro -> /gestao/ (resultado, margem, conciliação; Balancete fica linkado de lá). management.index só faz as consultas financeiras quando secao=financeiro. lshub-ui.js compara o parâmetro secao para destacar o menu certo. A Central fiscal em uso é fiscal/center.html (render_fiscal_center); fiscal/index.html era morto e foi apagado. Exportar XML (ZIP) mora na Central fiscal. Histórico é página própria linkada das Configurações: os iframes de Configurações não carregam porque security.py manda X-Frame-Options DENY e frame-ancestors 'none' (teste test_review_regressions exige isso), então não embutir páginas novas lá.
