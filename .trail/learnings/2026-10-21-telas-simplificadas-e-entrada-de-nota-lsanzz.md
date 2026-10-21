---
title: Telas simplificadas e entrada de nota única
author: Lsanzz
date: 2026-10-21
branch: master
touches:
  - app/templates/operacao/inventory.html
  - app/static/polish.css
  - app/web.py
---

Entrada de nota é um só diálogo #stock-entry em /operacao/estoque (XML -> products_import_xml_preview/confirm, ou manual -> inventory_receive); Peças e Financeiro só linkam para /operacao/estoque#lancar. As rotas antigas /produtos/importar-xml e /financeiro/importar-xml/* (só financeiro) foram removidas; a API /api/financeiro/importar-xml continua. O form de XML aparece só para ADMINISTRADOR porque a rota é admin_required. Armadilhas: (1) CSS inline em template Jinja com '{#id' abre comentário Jinja e dá 500 - escreva '{ #id'. (2) theme.css tem '.main a:not([class])' que força padding em links sem classe; links em abas/menus precisam de class (ex.: class="tab"). (3) stock-entry.js deve achar o form manual por [data-stock-rows], pois o 1º form do diálogo é o do XML. Abas de seção: financeiro/_tabs.html e relatorios/_tabs.html substituem itens de menu.
