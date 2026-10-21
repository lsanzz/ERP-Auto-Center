---
title: Cartão da O.S. do assistente editável
author: Lsanzz
date: 2026-10-21
branch: feat/assistant-card-edit
touches:
  - app/assistant/tools.py
  - app/assistant/routes.py
  - app/static/assistant.js
  - app/static/assistant.css
  - tests/test_assistant.py
---

## Decided
- O cartão de nova O.S. (propor_os) permite trocar variante, mudar quantidade e remover item. Preço e desconto não são editáveis, e não dá para adicionar item pelo cartão (o usuário pede no chat). O cartão de alteração de O.S. não é editável.
- Variantes vêm de `_alternatives`: itens ativos do mesmo tipo que contêm a primeira palavra não genérica do nome (GENERIC_WORDS ignora TROCA, SERVICO, KIT, JOGO...). São no máximo 6, e a lista inclui o próprio item.
- Ao confirmar, o navegador envia `itens: [{indice, catalogo_id, quantidade}]`. `edit_draft_items` aceita só índices do rascunho e variantes que estão em `draft['opcoes']`, e então refaz tudo por `_resolve_items`. Variante nova usa o preço do catálogo. A original mantém o preço e o desconto da proposta.
- Nome ambíguo continua virando pergunta da IA (`_catalog_match`). O cartão não substitui essa pergunta.

## Watch out
- A sessão Flask é cookie (limite de ~4KB e já guarda ai_history). Por isso só os ids das opções vão para o rascunho. Nomes e preços vão apenas na resposta do cartão.
- `routes._recent` (rate limit de 12/min) é global ao processo. tests/test_assistant.py zera esse contador no setUp; sem isso, testes com várias mensagens dão 429.
- Remover item usa setTimeout, não animationend. Sem animação (reduced motion ou aba oculta), o evento não dispara e o item ficaria na tela.
