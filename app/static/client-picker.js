// Busca de cliente sob demanda: evita enviar a lista inteira de clientes no HTML.
document.querySelectorAll('[data-client-picker]').forEach((wrapper) => {
  const search = wrapper.querySelector('input[type="text"]');
  const hidden = wrapper.querySelector('input[type="hidden"]');
  const box = wrapper.querySelector('.custom-suggestions-box');
  const help = wrapper.parentElement.querySelector('.entity-autocomplete-help');
  const freeText = wrapper.hasAttribute('data-free-text');
  const normalize = (value) => (value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toUpperCase();
  let selectedLabel = hidden.value ? search.value : '';
  let pending;
  let timer;
  let activeIndex = -1;

  // Sem texto livre, o nome digitado precisa vir de um cadastro escolhido na lista.
  function validate() {
    if (freeText) return;
    const missing = (search.required || search.value.trim()) && !hidden.value;
    search.setCustomValidity(missing ? 'Selecione um cliente da lista.' : '');
  }

  function close() {
    box.style.display = 'none';
    search.setAttribute('aria-expanded', 'false');
    activeIndex = -1;
  }

  function setClient(id, label) {
    const changed = hidden.value !== String(id);
    hidden.value = id;
    selectedLabel = label;
    validate();
    if (changed) hidden.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function choose(button) {
    search.value = button.dataset.name.toUpperCase();
    setClient(button.dataset.id, search.value);
    help.textContent = 'Cliente cadastrado selecionado.';
    close();
  }

  function render(items) {
    box.replaceChildren();
    for (const client of items) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'custom-suggestion-item';
      button.setAttribute('role', 'option');
      button.dataset.id = client.id;
      button.dataset.name = client.nome;
      const copy = document.createElement('span');
      copy.className = 'custom-suggestion-copy';
      const title = document.createElement('strong');
      title.textContent = client.nome;
      const detail = document.createElement('small');
      detail.textContent = client.detalhe || 'Cliente cadastrado';
      copy.append(title, detail);
      const action = document.createElement('span');
      action.className = 'custom-suggestion-action';
      action.textContent = 'Selecionar';
      button.append(copy, action);
      button.addEventListener('mousedown', (event) => {
        event.preventDefault();
        choose(button);
      });
      box.append(button);
    }
    if (!items.length) {
      close();
      help.textContent = freeText
        ? 'Nenhum cadastro encontrado. O nome digitado criará um novo cliente.'
        : 'Nenhum cliente encontrado.';
      return;
    }
    box.style.display = 'block';
    search.setAttribute('aria-expanded', 'true');
    help.textContent = `${items.length} cliente${items.length === 1 ? '' : 's'} encontrado${items.length === 1 ? '' : 's'}.`;
  }

  async function load() {
    if (pending) pending.abort();
    pending = new AbortController();
    try {
      const response = await fetch('/clientes/buscar?' + new URLSearchParams({ q: search.value.trim() }), { signal: pending.signal });
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error();
      render((await response.json()).items || []);
    } catch (error) {
      if (error.name !== 'AbortError') {
        close();
        help.textContent = 'Não foi possível consultar os clientes. Tente novamente.';
      }
    }
  }

  search.addEventListener('input', () => {
    if (hidden.value && normalize(search.value) !== normalize(selectedLabel)) setClient('', '');
    validate();
    clearTimeout(timer);
    timer = setTimeout(load, 220);
  });
  search.addEventListener('focus', () => { if (!hidden.value) load(); });
  search.addEventListener('blur', () => setTimeout(close, 160));
  search.addEventListener('keydown', (event) => {
    const options = Array.from(box.querySelectorAll('.custom-suggestion-item'));
    if (event.key === 'Escape') return close();
    if (box.style.display !== 'block' || !['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key) || !options.length) return;
    event.preventDefault();
    if (event.key === 'Enter') return choose(options[activeIndex >= 0 ? activeIndex : 0]);
    activeIndex = event.key === 'ArrowUp'
      ? (activeIndex <= 0 ? options.length - 1 : activeIndex - 1)
      : (activeIndex + 1) % options.length;
    options.forEach((option, index) => option.setAttribute('aria-selected', index === activeIndex ? 'true' : 'false'));
    options[activeIndex].scrollIntoView({ block: 'nearest' });
  });
  validate();
});
