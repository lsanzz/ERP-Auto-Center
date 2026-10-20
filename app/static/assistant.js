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
    if (draft.itens) {
      const table = el('table');
      draft.itens.forEach(item => {
        const tr = el('tr');
        tr.append(el('td', `${item.quantidade} × ${item.descricao}${item.desconto ? ` (desc. ${money(item.desconto)})` : ''}`));
        const td = el('td', money(item.total)); td.className = 'num'; tr.append(td);
        table.append(tr);
      });
      wrap.append(table);
    }
    const total = el('p', `Total: ${money(draft.total)}`); total.className = 'ai-total'; wrap.append(total);
    (draft.avisos || []).forEach(text => { const w = el('p', `⚠ ${text}`); w.className = 'ai-warn'; wrap.append(w); });
    const buttons = el('div'); buttons.className = 'ai-buttons';
    const ok = el('button', 'Confirmar'); ok.type = 'button';
    const cancel = el('button', 'Cancelar'); cancel.type = 'button'; cancel.className = 'secondary';
    buttons.append(ok, cancel); wrap.append(buttons);
    ok.addEventListener('click', async () => {
      ok.disabled = cancel.disabled = true;
      const {ok: success, data} = await post(panel.dataset.confirm.replace('__ID__', draft.draft_id));
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
      ok.disabled = cancel.disabled = true;
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
  if (saved) { log.innerHTML = saved; log.querySelectorAll('.ai-buttons').forEach(node => node.remove()); }

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
