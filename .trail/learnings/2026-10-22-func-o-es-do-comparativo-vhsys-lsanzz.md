---
title: Funções do comparativo vhsys
author: Lsanzz
date: 2026-10-22
branch: master
touches:
  - app/models.py
  - app/services.py
  - app/web.py
  - app/management.py
  - scripts/add_work_order_details.py
  - scripts/backfill_categories.py
---

O.S. ganhou desconto geral (recalculate_work_order_totals subtrai e rejeita desconto > itens), tipo_atendimento, problema_relatado, laudo e observacoes_cliente; o PDF imprime observacoes_cliente (cai para observacoes nas O.S. antigas) e ?producao=1 gera a ordem de produção sem preços. Banco de produção: rodar scripts/add_work_order_details.py (idempotente; ajusta alembic_version só se estiver em 20260924_17) em vez de db_upgrade às cegas, porque não se sabe se o MySQL tem alembic_version. Categoria: FinancialEntry tem before_insert que preenche categoria vazia por default_category (OS -> Ordens de Serviço, XML_NFE/ENTRADA_ESTOQUE -> Compra de peças); o relatório financeiro agrupa por categoria (DRE: Receitas, Despesas fixas por palavra-chave, variáveis) e não por plano de contas, que quase nunca é preenchido. scripts/backfill_categories.py preenche os antigos (prévia; --apply grava). Saldos usam data-private + classe show-money no <html> (localStorage). Bug corrigido: form de O.S. nova com erro de validação dava 500 ao montar link do PDF sem id. Desconto geral não vai automático para NF-e/NFS-e: a prévia da nota mostra aviso.
