document.addEventListener('DOMContentLoaded', () => {
  const vehicleId = document.getElementById('vehicle_id');
  const clientId = document.getElementById('client_id');
  const search = document.getElementById('vehicle-search');
  const box = document.getElementById('vehicle-suggestions');
  const help = document.getElementById('vehicle-help');
  const plate = document.getElementById('placa');
  const description = document.getElementById('veiculo_descricao');
  if (!vehicleId || !clientId || !search || !box || !help) return;

  let pending;
  let timer;
  let activeIndex = -1;
  let selectedLabel = search.value;

  function close() {
    box.style.display = 'none';
    search.setAttribute('aria-expanded', 'false');
    activeIndex = -1;
  }

  function visibleOptions() {
    return Array.from(box.querySelectorAll('.vehicle-suggestion'));
  }

  function choose(button) {
    vehicleId.value = button.dataset.id;
    selectedLabel = button.dataset.label;
    search.value = selectedLabel;
    if (plate) plate.value = button.dataset.plate || '';
    if (description) description.value = button.dataset.description || '';
    help.textContent = 'Veículo cadastrado selecionado.';
    close();
  }

  function render(items) {
    box.replaceChildren();
    for (const vehicle of items) {
      const label = `${vehicle.placa || 'SEM PLACA'} · ${vehicle.descricao}`;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'custom-suggestion-item vehicle-suggestion';
      button.dataset.id = vehicle.id;
      button.dataset.plate = vehicle.placa || '';
      button.dataset.description = vehicle.descricao;
      button.dataset.label = label;
      const copy = document.createElement('span');
      copy.className = 'custom-suggestion-copy';
      const title = document.createElement('strong');
      title.textContent = vehicle.placa || 'SEM PLACA';
      const detail = document.createElement('small');
      detail.textContent = vehicle.descricao;
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
      help.textContent = 'Nenhum veículo encontrado. Preencha placa e descrição manualmente.';
      return;
    }
    if (document.activeElement === search) {  // só abre a lista quando a pessoa está no campo
      box.style.display = 'block';
      search.setAttribute('aria-expanded', 'true');
    }
    help.textContent = `${items.length} veículo${items.length === 1 ? '' : 's'} encontrado${items.length === 1 ? '' : 's'}.`;
  }

  async function load(query = search.value) {
    if (pending) pending.abort();
    if (!clientId.value) {
      box.replaceChildren();
      close();
      help.textContent = 'Selecione um cliente para localizar seus veículos.';
      return;
    }
    pending = new AbortController();
    help.textContent = 'Buscando veículos…';
    try {
      const params = new URLSearchParams({ client_id: clientId.value, q: query.trim() });
      const response = await fetch('/veiculos/buscar?' + params, { signal: pending.signal });
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error();
      const data = await response.json();
      render(data.items || []);
    } catch (error) {
      if (error.name !== 'AbortError') {
        close();
        help.textContent = 'Não foi possível consultar os veículos. Tente novamente.';
      }
    }
  }

  clientId.addEventListener('change', () => {
    if (vehicleId.value) {
      vehicleId.value = '';
      search.value = '';
      selectedLabel = '';
      if (plate) plate.value = '';
      if (description) description.value = '';
    }
    load('');
  });
  search.addEventListener('input', () => {
    if (search.value !== selectedLabel) vehicleId.value = '';
    clearTimeout(timer);
    timer = setTimeout(() => load(search.value), 220);
  });
  search.addEventListener('focus', () => load(vehicleId.value ? '' : search.value));
  search.addEventListener('blur', () => setTimeout(close, 160));
  search.addEventListener('keydown', (event) => {
    const options = visibleOptions();
    if (event.key === 'Escape') return close();
    if (!['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key) || !options.length) return;
    event.preventDefault();
    if (event.key === 'Enter') return choose(options[activeIndex >= 0 ? activeIndex : 0]);
    activeIndex = event.key === 'ArrowUp'
      ? (activeIndex <= 0 ? options.length - 1 : activeIndex - 1)
      : (activeIndex + 1) % options.length;
    options.forEach((option, index) => option.setAttribute('aria-selected', index === activeIndex ? 'true' : 'false'));
    options[activeIndex].scrollIntoView({ block: 'nearest' });
  });

  load('');
});
