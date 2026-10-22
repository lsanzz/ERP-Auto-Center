// Consulta de placa: máscara da placa, scanner durante a busca, resultado em cartões e consultas recentes.
// Dados da API externa entram sempre por textContent (nunca innerHTML).
(() => {
  const page = document.querySelector('.plate-page');
  if (!page) return;
  const form = document.getElementById('plate-form');
  const input = document.getElementById('plate-input');
  const button = document.getElementById('plate-button');
  const status = document.getElementById('plate-status');
  const result = document.getElementById('plate-result');
  const recent = document.getElementById('plate-recent');
  const KEY = 'lshub-placas-recentes';
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const money = value => Number(value || 0).toLocaleString('pt-BR', {style: 'currency', currency: 'BRL'});

  const ICONS = {  // SVGs fixos do próprio sistema
    ano: '<path d="M7 3v3M17 3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/>',
    combustivel: '<path d="M4 20V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v15M3 20h12M6 8h6M14 9l3-2 2 2v8a1.5 1.5 0 0 1-3 0v-3h-2"/>',
    motor: '<path d="M4 10h3l2-3h5l2 3h2v6h-2l-2 2H9l-2-2H4zM1 12v2M21 11v4"/>',
    potencia: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    cor: '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.5-.9 1-1.8-.6-1-.1-2.2 1.1-2.2H17a4 4 0 0 0 4-4c0-5-4-10-9-10z"/>',
    cidade: '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
    tipo: '<path d="M5 16l1.5-5A2 2 0 0 1 8.4 9.5h7.2a2 2 0 0 1 1.9 1.5L19 16M3 16h18v3H3zM7 19v2M17 19v2"/>',
    pessoas: '<circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0 1 12 0M16 11a3 3 0 1 0 0-6M21 20a5 5 0 0 0-4-4.9"/>',
    chassi: '<path d="M4 7h16M4 12h16M4 17h10"/>',
    origem: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  };
  const COLORS = {preta: '#111827', preto: '#111827', branca: '#f8fafc', branco: '#f8fafc', prata: '#c0c4c8', cinza: '#8a8f98',
    vermelha: '#c62828', vermelho: '#c62828', azul: '#1e40af', verde: '#15803d', amarela: '#facc15', amarelo: '#facc15',
    bege: '#d6c7a1', marrom: '#6b4423', dourada: '#c9a227', dourado: '#c9a227', laranja: '#ea580c', vinho: '#7f1d1d',
    rosa: '#ec4899', roxa: '#7c3aed', roxo: '#7c3aed', grena: '#7f1d1d'};
  const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  const icon = name => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.8'); svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true'); svg.innerHTML = ICONS[name] || ICONS.tipo;
    return svg;
  };
  const clean = value => (value || '').replace(/[^a-zA-Z0-9]/g, '').toUpperCase().slice(0, 7);
  const show = value => value.length > 3 ? `${value.slice(0, 3)}-${value.slice(3)}` : value;  // exibe com hífen, envia sem

  input.addEventListener('input', () => { input.value = show(clean(input.value)); });

  const loadRecent = () => { try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (_) { return []; } };
  const renderRecent = () => {
    const items = loadRecent();
    recent.hidden = !items.length;
    recent.querySelectorAll('button').forEach(node => node.remove());
    items.forEach(plate => {
      const chip = el('button', show(plate)); chip.type = 'button';
      chip.addEventListener('click', () => { input.value = show(plate); form.requestSubmit(); });
      recent.append(chip);
    });
  };
  const remember = plate => {
    const items = [plate, ...loadRecent().filter(item => item !== plate)].slice(0, 6);
    try { localStorage.setItem(KEY, JSON.stringify(items)); } catch (_) {}
    renderRecent();
  };

  const countUp = (node, text) => {
    const target = Number(String(text).replace(/[^\d,]/g, '').replace(',', '.'));
    if (!target || reduceMotion) { node.textContent = text; return; }
    const start = performance.now();
    const step = now => {
      const progress = Math.min(1, (now - start) / 900);
      node.textContent = money(target * (1 - Math.pow(1 - progress, 3)));
      if (progress < 1) requestAnimationFrame(step); else node.textContent = text;
    };
    requestAnimationFrame(step);
  };

  const spec = (name, label, value, index) => {
    const card = el('div', undefined, 'plate-spec rise-in'); card.style.setProperty('--i', index + 1);
    card.append(icon(name), el('small', label), el('strong', value));
    return card;
  };

  const render = (data, plate) => {
    const d = data.detalhes || {};
    result.hidden = false;
    result.querySelector('.plate-main').hidden = false;
    result.querySelectorAll('.rise-in').forEach(node => { node.style.animation = 'none'; void node.offsetWidth; node.style.animation = ''; });
    document.getElementById('plate-alert').hidden = !data.alerta_roubo;
    document.getElementById('plate-chip').textContent = show(data.placa || plate);
    const title = [d.marca, d.modelo].filter(Boolean).join(' ') || data.veiculo_descricao || 'Veículo sem descrição';
    document.getElementById('plate-title').textContent = title;
    const years = [d.ano_fabricacao, d.ano_modelo].filter(Boolean);
    document.getElementById('plate-subtitle').textContent = [d.versao, years.length ? years.join('/') : ''].filter(Boolean).join(' · ') || ' ';
    const color = document.getElementById('plate-color');
    color.hidden = !d.cor;
    if (d.cor) { color.querySelector('b').textContent = d.cor; color.querySelector('i').style.background = COLORS[d.cor.toLowerCase().split(/[\s/]/)[0]] || '#94a3b8'; }

    const actions = document.getElementById('plate-actions'); actions.replaceChildren();
    const description = data.veiculo_descricao || title;
    if (page.dataset.newOs) {
      const link = el('a', 'Abrir O.S. com esta placa', 'action');
      link.href = `${page.dataset.newOs}?${new URLSearchParams({placa: data.placa || plate, veiculo: description})}`;
      actions.append(link);
    }
    if (page.dataset.newVehicle) {
      const link = el('a', 'Cadastrar veículo', 'action ghost');
      link.href = `${page.dataset.newVehicle}?${new URLSearchParams({placa: data.placa || plate, descricao: description, marca: d.marca || '', modelo: d.modelo || ''})}`;
      actions.append(link);
    }

    const specs = [
      ['ano', 'Ano fab./modelo', years.join(' / ')], ['combustivel', 'Combustível', d.combustivel],
      ['motor', 'Motor', d.cilindradas ? `${d.cilindradas} cc` : ''], ['potencia', 'Potência', d.potencia ? `${d.potencia} cv` : ''],
['cor', 'Cor', d.cor], ['cidade', 'Cidade', [d.municipio, d.uf].filter(Boolean).join(' / ')],
      ['tipo', 'Tipo', d.tipo], ['pessoas', 'Passageiros', d.passageiros], ['origem', 'Origem', d.nacionalidade],
      ['chassi', 'Chassi (final)', d.chassi_final ? `…${d.chassi_final}` : ''], ['tipo', 'Situação', d.situacao],
    ].filter(([, , value]) => value);
    document.getElementById('plate-specs').replaceChildren(...specs.map(([name, label, value], index) => spec(name, label, value, index)));

    const fipe = document.getElementById('plate-fipe');
    fipe.hidden = !data.fipe;
    if (data.fipe) {
      countUp(fipe.querySelector('[data-fipe-value]'), data.fipe.valor);
      fipe.querySelector('[data-fipe-model]').textContent = [data.fipe.modelo, data.fipe.referencia && `Referência ${data.fipe.referencia}`].filter(Boolean).join(' · ');
    }
    renderHistory(data.historico);
  };

  const renderHistory = history => {
    const box = document.getElementById('plate-history');
    box.hidden = !history;
    if (!history) return;
    box.querySelector('[data-history-title]').textContent = history.total
      ? `${history.total} O.S. · ${history.cliente || 'cliente não informado'}` : 'Primeira vez na oficina';
    const list = box.querySelector('[data-history-list]');
    list.replaceChildren(...history.ordens.map(order => {
      const item = el('li'); const link = el('a', undefined, 'history-row'); link.href = order.url;
      const date = order.data ? new Date(`${order.data}T12:00:00`).toLocaleDateString('pt-BR') : '';
      link.append(el('b', `O.S. ${order.numero}`), el('span', `${date} · ${order.status.replace(/_/g, ' ').toLowerCase()}`), el('b', money(order.total)));
      item.append(link); return item;
    }));
  };

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const plate = clean(input.value);
    status.className = 'plate-status';
    if (plate.length !== 7) { status.textContent = 'A placa tem 7 caracteres, por exemplo ABC1D23.'; status.classList.add('is-error'); return; }
    button.disabled = true; page.classList.add('is-scanning');
    status.textContent = 'Consultando…';
    try {
      const response = await fetch(`/api/veiculos/placa/${encodeURIComponent(plate)}`, {credentials: 'same-origin'});
      const data = await response.json().catch(() => ({error: 'Resposta inválida do servidor.'}));
      if (!response.ok) {
        status.textContent = data.error || 'Não foi possível consultar a placa.'; status.classList.add('is-error');
        result.hidden = !data.historico?.total;  // mesmo sem a API, mostra o que a oficina já sabe
        if (data.historico?.total) {
          ['plate-alert', 'plate-fipe'].forEach(id => { document.getElementById(id).hidden = true; });
          result.querySelector('.plate-main').hidden = true;
          document.getElementById('plate-specs').replaceChildren();
          renderHistory(data.historico);
        }
        return;
      }
      render(data, plate);
      remember(data.placa || plate);
      status.textContent = 'Consulta concluída.'; status.classList.add('is-ok');
      if (!reduceMotion) result.scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (_) {
      status.textContent = 'Sem conexão com o servidor. Tente de novo.'; status.classList.add('is-error');
    } finally {
      button.disabled = false; page.classList.remove('is-scanning');
    }
  });

  renderRecent();
  const preset = clean(new URLSearchParams(location.search).get('placa'));
  if (preset.length === 7) { input.value = show(preset); form.requestSubmit(); }
  else input.focus();
})();
