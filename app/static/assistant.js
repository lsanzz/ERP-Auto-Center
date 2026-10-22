// Painel do assistente: conversa, cartões de proposta (Confirmar/Cancelar) e microfone quando o navegador suporta.
(() => {
  const panel = document.getElementById('ai-panel');
  if (!panel) return;
  const launcher = document.querySelector('[data-ai-open]');
  const log = panel.querySelector('.ai-log');
  const form = panel.querySelector('[data-ai-form]');
  const box = form.elements.texto;
  const money = value => Number(value || 0).toLocaleString('pt-BR', {style: 'currency', currency: 'BRL'});
  const STORE = 'lshub-ai-log';

  const post = (url, body) => fetch(url, {
    method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json', 'X-CSRFToken': panel.dataset.csrf},
    body: JSON.stringify(body || {}),
  }).then(async response => ({ok: response.ok, data: await response.json().catch(() => ({erro: 'Resposta inválida do servidor.'}))}));

  const save = () => sessionStorage.setItem(STORE, log.innerHTML);
  const add = (text, kind) => {
    const p = document.createElement('p');
    p.className = `ai-msg ai-${kind}`;
    p.textContent = String(text).replace(/\*\*(.+?)\*\*/g, '$1');  // o modelo às vezes manda **negrito** em markdown
    log.append(p);
    log.scrollTop = log.scrollHeight;
    save();
    return p;
  };
  const el = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };

  const card = draft => {
    const wrap = el('div'); wrap.className = 'ai-card';
    wrap.append(el('h4', draft.tipo === 'criar_os' ? 'Nova O.S. — confira antes de salvar' : `Alterar O.S. ${draft.numero}`));
    const dl = el('dl');
    const row = (label, value) => { if (value === null || value === undefined || value === '') return; dl.append(el('dt', label), el('dd', String(value))); };
    row('Cliente', draft.cliente); row('Placa', draft.placa); row('Veículo', draft.veiculo);
    row('Pagamento', draft.parcelas > 1 ? `${draft.forma_pagamento} em ${draft.parcelas}x` : draft.forma_pagamento);
    row('Responsável', draft.responsavel); row('Observações', draft.observacoes);
    if (draft.tipo === 'alterar_os') { row('Remover', (draft.removidos || []).join(', ')); row('Adicionar', (draft.adicionados || []).join(', ')); row('Total antes', money(draft.total_antes)); }
    wrap.append(dl);
    // Itens editáveis: variante (só entre as opções do servidor), quantidade e remover; o servidor revalida tudo ao confirmar.
    const items = (draft.itens || []).map((item, indice) => ({...item, indice, escolha: item.catalogo_id, qtd: item.quantidade}));
    const total = el('p'); total.className = 'ai-total';
    const lineTotal = item => {
      const option = (item.opcoes || []).find(o => o.id === item.escolha);
      return item.escolha === item.catalogo_id ? item.qtd * item.valor_unitario - item.desconto : item.qtd * option.preco;
    };
    const refresh = () => {
      total.textContent = `Total: ${money(items.reduce((sum, item) => sum + lineTotal(item), 0))}`;
      total.classList.remove('ai-bump'); void total.offsetWidth; total.classList.add('ai-bump');
      list.querySelectorAll('.ai-x').forEach(x => { x.disabled = items.length < 2; });
    };
    const list = el('ul'); list.className = 'ai-items';
    items.forEach(item => {
      const li = el('li'); li.className = 'ai-item';
      const name = el('span', item.descricao); name.className = 'ai-item-name';
      const remove = el('button', '×'); remove.type = 'button'; remove.className = 'ai-x'; remove.setAttribute('aria-label', `Remover ${item.descricao}`);
      const top = el('div'); top.className = 'ai-item-top'; top.append(name, remove); li.append(top);
      if (item.opcoes && item.opcoes.length) {
        const chips = el('div'); chips.className = 'ai-chips'; chips.setAttribute('role', 'group'); chips.setAttribute('aria-label', `Tipo de ${item.descricao}`);
        item.opcoes.forEach(option => {
          const chip = el('button', `${option.nome} · ${money(option.preco)}`); chip.type = 'button'; chip.className = 'ai-chip';
          chip.setAttribute('aria-pressed', String(option.id === item.escolha));
          chip.addEventListener('click', () => {
            item.escolha = option.id; name.textContent = option.nome;
            chips.querySelectorAll('.ai-chip').forEach(c => c.setAttribute('aria-pressed', String(c === chip)));
            price.textContent = money(lineTotal(item)); refresh();
          });
          chips.append(chip);
        });
        li.append(chips);
      }
      const qty = el('output', String(item.qtd));
      const minus = el('button', '−'); minus.type = 'button'; minus.setAttribute('aria-label', 'Diminuir quantidade');
      const plus = el('button', '+'); plus.type = 'button'; plus.setAttribute('aria-label', 'Aumentar quantidade');
      const step = delta => {
        item.qtd = Math.max(1, item.qtd + delta); qty.textContent = String(item.qtd); minus.disabled = item.qtd <= 1;
        price.textContent = money(lineTotal(item)); refresh();
      };
      minus.disabled = item.qtd <= 1;
      minus.addEventListener('click', () => step(-1)); plus.addEventListener('click', () => step(1));
      const stepper = el('div'); stepper.className = 'ai-step'; stepper.append(minus, qty, plus);
      const price = el('span', money(lineTotal(item))); price.className = 'num';
      const bottom = el('div'); bottom.className = 'ai-item-bottom'; bottom.append(stepper, price); li.append(bottom);
      remove.addEventListener('click', () => {
        items.splice(items.indexOf(item), 1); refresh();
        wrap.querySelectorAll('.ai-warn').forEach(w => { if (w.textContent.includes(`"${item.descricao}"`)) w.remove(); });  // aviso do item removido
        li.classList.add('ai-out'); setTimeout(() => li.remove(), 180);  // timer, não animationend: sem animação o evento não vem
      });
      list.append(li);
    });
    if (items.length) { wrap.append(list); refresh(); total.classList.remove('ai-bump'); } else total.textContent = `Total: ${money(draft.total)}`;
    wrap.append(total);
    (draft.avisos || []).forEach(text => { const w = el('p', `⚠ ${text}`); w.className = 'ai-warn'; wrap.append(w); });
    const buttons = el('div'); buttons.className = 'ai-buttons';
    const ok = el('button', 'Confirmar'); ok.type = 'button';
    const cancel = el('button', 'Cancelar'); cancel.type = 'button'; cancel.className = 'secondary';
    buttons.append(ok, cancel); wrap.append(buttons);
    ok.addEventListener('click', async () => {
      wrap.querySelectorAll('button').forEach(b => { b.disabled = true; });
      const body = items.length ? {itens: items.map(item => ({indice: item.indice, catalogo_id: item.escolha, quantidade: item.qtd}))} : {};
      const {ok: success, data} = await post(panel.dataset.confirm.replace('__ID__', draft.draft_id), body);
      buttons.remove();
      if (success) {
        const done = el('p'); done.className = 'ai-total';
        const link = el('a', `O.S. ${data.numero} salva (${money(data.total)}) — abrir`); link.href = data.url;
        done.append(link); wrap.append(done);
      } else {
        wrap.append(Object.assign(el('p', data.erro || 'Não foi possível salvar.'), {className: 'ai-warn'}));
      }
      save();
    });
    cancel.addEventListener('click', async () => {
      wrap.querySelectorAll('button').forEach(b => { b.disabled = true; });
      await post(panel.dataset.cancel.replace('__ID__', draft.draft_id));
      buttons.replaceWith(Object.assign(el('p', 'Proposta cancelada.'), {className: 'ai-warn'}));
      save();
    });
    log.append(wrap);
    log.scrollTop = log.scrollHeight;
  };

  const open = state => {
    panel.hidden = !state;
    launcher.setAttribute('aria-expanded', String(state));
    launcher.hidden = state;
    launcher.closest('details')?.removeAttribute('open');  // fecha o menu de atalhos
    if (state) box.focus();
  };
  launcher.addEventListener('click', () => open(true));
  panel.querySelector('[data-ai-close]').addEventListener('click', () => open(false));
  panel.querySelector('[data-ai-new]').addEventListener('click', async () => {
    await post(panel.dataset.new);
    sessionStorage.removeItem(STORE);
    log.querySelectorAll('.ai-msg:not(:first-child), .ai-card').forEach(node => node.remove());
  });

  // Histórico visual da aba; os botões de propostas antigas não funcionam após recarregar, então somem.
  const saved = sessionStorage.getItem(STORE);
  if (saved) { log.innerHTML = saved; log.querySelectorAll('.ai-buttons').forEach(node => node.remove()); log.querySelectorAll('.ai-card button').forEach(b => { b.disabled = true; }); }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const text = box.value.trim();
    if (!text) return;
    box.value = '';
    add(text, 'user');
    const waiting = add('Pensando…', 'bot');
    form.querySelector('[type=submit]').disabled = true;
    const {ok, data} = await post(panel.dataset.send, {texto: text});
    waiting.remove();
    form.querySelector('[type=submit]').disabled = false;
    if (!ok) { add(data.erro || 'Erro ao falar com o assistente.', 'error'); return; }
    add(data.texto, 'bot');
    (data.cartoes || []).forEach(card);
    save();
  });
  box.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
  });

  // Microfone próprio só onde a Web Speech API existe (Chrome/Edge); no Brave use o microfone do teclado.
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const mic = panel.querySelector('[data-ai-mic]');
  if (Recognition) {
    mic.hidden = false;
    const recognition = new Recognition();
    recognition.lang = 'pt-BR';
    recognition.interimResults = false;
    recognition.addEventListener('result', event => { box.value = (box.value + ' ' + event.results[0][0].transcript).trim(); });
    recognition.addEventListener('end', () => mic.classList.remove('listening'));
    mic.addEventListener('click', () => { mic.classList.add('listening'); recognition.start(); });
  }
})();
