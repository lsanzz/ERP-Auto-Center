---
title: Consulta de placa e situação na lista
author: Lsanzz
date: 2026-10-22
branch: master
touches:
  - app/vehicles.py
  - app/api.py
  - app/static/placa.js
  - app/templates/os/index.html
---

API de placa (wdapi2/apiplacas): resposta real tem MARCA/MODELO/SUBMODELO/ano/anoModelo/cor/municipio/uf/situacao no topo, detalhes em extra.* (combustivel, cilindradas, tipo_veiculo, quantidade_passageiro, nacionalidade) e fipe.dados[] com score; extra.caixa_cambio é número de série, não tipo de câmbio. O .env local TEM token: testes devem mockar app.api.lookup_plate para não gastar consulta. /api/veiculos/placa devolve historico (O.S. da placa) mesmo quando a API falha. Lista de O.S.: menu na etiqueta de situação posta para /os/<id>/status ou /os/<id>/responsavel com next=request.full_path e volta para #os-<id> (safe_next_url). Botões recolhíveis usam o padrão em polish.css para .hub-advanced/.finance-more/.nota-details/.fiscal-fold/.toggle-details > summary; 'Mais filtros' usa summary.filter-toggle e .toggle-count.
