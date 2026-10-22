document.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', () => {
  const dialog = document.getElementById(button.dataset.open);
  const type = dialog.querySelector('[name="entry_type"]');
  if (type && button.dataset.entryType) type.value = button.dataset.entryType;
  dialog.showModal();
}));
// Forma de pagamento escolhe a conta: Dinheiro → Dinheiro; Pix/cartão → JURIDICA (pode ser trocada).
document.querySelectorAll('form[data-method-accounts]').forEach(form => {
  const accounts = JSON.parse(form.dataset.methodAccounts || '{}');
  const method = form.elements.payment_method_id;
  const account = form.elements.bank_account_id;
  if (!method || !account) return;
  method.addEventListener('change', () => {
    if (accounts[method.value]) account.value = String(accounts[method.value]);
  });
});
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('.hub-settle').forEach(form => {
  const update = () => {
    const value = name => {
      const raw = (form.elements[name]?.value || '').trim();
      const normalized = raw.includes(',') ? raw.replace(/\./g, '').replace(',', '.') : raw;
      const number = Number(normalized);
      return Number.isFinite(number) ? number : 0;
    };
    const amount = value('valor_baixa') + value('juros') - value('desconto') - value('taxa') + value('acrescimo');
    form.querySelector('output').textContent = amount.toLocaleString('pt-BR', {style:'currency',currency:'BRL'});
  };
  form.addEventListener('input', update);
  update();
});

(() => {
  const dateInputs = document.querySelectorAll('.hub-filters input[type="date"]');
  if (!dateInputs.length) return;

  const monthFormatter = new Intl.DateTimeFormat('pt-BR', {month: 'long', year: 'numeric'});
  const fullDateFormatter = new Intl.DateTimeFormat('pt-BR');
  let openCalendar = null;

  const parseDate = value => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
    return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
  };
  const dateValue = value => [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, '0'),
    String(value.getDate()).padStart(2, '0'),
  ].join('-');
  const sameDay = (first, second) => first && second && dateValue(first) === dateValue(second);
  const addDays = (value, amount) => new Date(value.getFullYear(), value.getMonth(), value.getDate() + amount);

  const close = calendar => {
    if (!calendar) return;
    calendar.panel.hidden = true;
    calendar.trigger.setAttribute('aria-expanded', 'false');
    calendar.wrapper.classList.remove('is-open');
    if (openCalendar === calendar) openCalendar = null;
  };

  dateInputs.forEach((input, index) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'finance-date-field';
    input.before(wrapper);
    wrapper.append(input);
    input.classList.add('finance-date-native');

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'finance-date-trigger';
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-controls', `finance-calendar-${index}`);
    trigger.innerHTML = '<span></span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3v3m10-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1Z"/></svg>';
    wrapper.append(trigger);

    const panel = document.createElement('div');
    panel.id = `finance-calendar-${index}`;
    panel.className = 'finance-date-popover';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Escolher data');
    panel.hidden = true;
    panel.innerHTML = `
      <div class="finance-calendar-head">
        <button type="button" class="finance-calendar-nav prev" aria-label="Mês anterior"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg></button>
        <strong class="finance-calendar-month" aria-live="polite"></strong>
        <button type="button" class="finance-calendar-nav next" aria-label="Próximo mês"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg></button>
      </div>
      <div class="finance-calendar-week" aria-hidden="true"><span>Seg</span><span>Ter</span><span>Qua</span><span>Qui</span><span>Sex</span><span>Sáb</span><span>Dom</span></div>
      <div class="finance-calendar-grid" role="grid"></div>
      <div class="finance-calendar-footer"><button type="button" class="finance-calendar-clear">Limpar</button><button type="button" class="finance-calendar-today">Hoje</button></div>`;
    wrapper.append(panel);

    const selected = parseDate(input.value);
    const calendar = {
      input,
      wrapper,
      trigger,
      panel,
      grid: panel.querySelector('.finance-calendar-grid'),
      monthLabel: panel.querySelector('.finance-calendar-month'),
      viewed: selected || new Date(),
      min: parseDate(input.min),
      max: parseDate(input.max),
    };

    const updateTrigger = () => {
      const value = parseDate(input.value);
      trigger.querySelector('span').textContent = value ? fullDateFormatter.format(value) : 'dd/mm/aaaa';
      trigger.classList.toggle('has-value', Boolean(value));
      trigger.setAttribute('aria-label', value ? `Data selecionada: ${fullDateFormatter.format(value)}` : 'Escolher data');
    };

    const render = direction => {
      const year = calendar.viewed.getFullYear();
      const month = calendar.viewed.getMonth();
      const monthName = monthFormatter.format(new Date(year, month, 1));
      calendar.monthLabel.textContent = monthName.charAt(0).toUpperCase() + monthName.slice(1);
      const firstDay = new Date(year, month, 1);
      const offset = (firstDay.getDay() + 6) % 7;
      const firstVisible = addDays(firstDay, -offset);
      const selectedDate = parseDate(input.value);
      const today = new Date();
      const grid = document.createElement('div');
      grid.className = `finance-calendar-grid${direction ? ` move-${direction}` : ''}`;
      grid.setAttribute('role', 'grid');

      for (let position = 0; position < 42; position += 1) {
        const day = addDays(firstVisible, position);
        const iso = dateValue(day);
        const disabled = (calendar.min && day < calendar.min) || (calendar.max && day > calendar.max);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'finance-calendar-day';
        button.textContent = String(day.getDate());
        button.dataset.date = iso;
        button.setAttribute('role', 'gridcell');
        button.setAttribute('aria-label', fullDateFormatter.format(day));
        button.disabled = Boolean(disabled);
        if (day.getMonth() !== month) button.classList.add('is-adjacent');
        if (sameDay(day, today)) button.classList.add('is-today');
        if (sameDay(day, selectedDate)) {
          button.classList.add('is-selected');
          button.setAttribute('aria-selected', 'true');
        }
        button.addEventListener('click', () => {
          input.value = iso;
          input.dispatchEvent(new Event('change', {bubbles: true}));
          updateTrigger();
          close(calendar);
          trigger.focus();
        });
        grid.append(button);
      }
      calendar.grid.replaceWith(grid);
      calendar.grid = grid;
    };

    const moveMonth = amount => {
      calendar.viewed = new Date(calendar.viewed.getFullYear(), calendar.viewed.getMonth() + amount, 1);
      render(amount > 0 ? 'next' : 'prev');
    };

    panel.querySelector('.prev').addEventListener('click', () => moveMonth(-1));
    panel.querySelector('.next').addEventListener('click', () => moveMonth(1));
    panel.querySelector('.finance-calendar-clear').addEventListener('click', () => {
      input.value = '';
      input.dispatchEvent(new Event('change', {bubbles: true}));
      updateTrigger();
      close(calendar);
      trigger.focus();
    });
    panel.querySelector('.finance-calendar-today').addEventListener('click', () => {
      const today = new Date();
      input.value = dateValue(today);
      input.dispatchEvent(new Event('change', {bubbles: true}));
      calendar.viewed = today;
      updateTrigger();
      close(calendar);
      trigger.focus();
    });

    panel.addEventListener('keydown', event => {
      const focused = event.target.closest('.finance-calendar-day');
      if (event.key === 'Escape') {
        close(calendar);
        trigger.focus();
        return;
      }
      if (!focused) return;
      const movements = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7};
      if (!(event.key in movements)) return;
      event.preventDefault();
      const targetDate = addDays(parseDate(focused.dataset.date), movements[event.key]);
      if (targetDate.getMonth() !== calendar.viewed.getMonth()) {
        calendar.viewed = targetDate;
        render(movements[event.key] > 0 ? 'next' : 'prev');
      }
      calendar.grid.querySelector(`[data-date="${dateValue(targetDate)}"]:not(:disabled)`)?.focus();
    });

    trigger.addEventListener('click', () => {
      if (openCalendar && openCalendar !== calendar) close(openCalendar);
      if (!panel.hidden) {
        close(calendar);
        return;
      }
      calendar.viewed = parseDate(input.value) || new Date();
      render();
      panel.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      wrapper.classList.add('is-open');
      openCalendar = calendar;
      panel.classList.remove('align-right');
      if (panel.getBoundingClientRect().right > window.innerWidth - 12) panel.classList.add('align-right');
      requestAnimationFrame(() => (calendar.grid.querySelector('.is-selected') || calendar.grid.querySelector('.is-today') || calendar.grid.querySelector('button:not(:disabled)'))?.focus());
    });

    updateTrigger();
    render();
  });

  document.addEventListener('pointerdown', event => {
    if (openCalendar && !openCalendar.wrapper.contains(event.target)) close(openCalendar);
  });
})();
// Atalho "+ Novo → Lançamento financeiro" do topo abre o formulário direto.
if (location.hash === '#novo') document.getElementById('new-entry')?.showModal();
