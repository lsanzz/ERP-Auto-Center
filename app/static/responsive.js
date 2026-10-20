/* Progressive enhancement: navigation remains accessible without JavaScript. */
(() => {
  const toggle = document.querySelector('.mobile-nav-toggle');
  const navigation = document.getElementById('main-navigation');
  const mobile = window.matchMedia('(max-width: 700px)');
  if (toggle && navigation) {
    const setOpen = (open, restoreFocus = false) => {
      navigation.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', String(open));
      toggle.querySelector('.mobile-nav-state').textContent = open ? '−' : '+';
      if (!open) navigation.querySelectorAll('details[open]').forEach(group => { group.open = false; });
      if (restoreFocus) toggle.focus();
    };
    document.documentElement.classList.add('mobile-nav-ready');
    toggle.addEventListener('click', () => setOpen(toggle.getAttribute('aria-expanded') !== 'true'));
    navigation.addEventListener('click', event => {
      if (mobile.matches && event.target.closest('a')) setOpen(false);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && mobile.matches && navigation.classList.contains('is-open')) setOpen(false, true);
    });
    mobile.addEventListener('change', () => {
      const hadFocus = navigation.contains(document.activeElement);
      setOpen(false, mobile.matches && hadFocus);
    });
  }

  const main = document.querySelector('body > .container > .main, .admin-main');
  if (!main) return;
  const prepared = new WeakSet();
  const labelRecords = table => {
    if (!table.matches('[data-mobile-cards]')) return;
    const headings = [...(table.tHead?.rows[0]?.cells || [])].map(cell => cell.textContent.trim());
    table.setAttribute('role', 'table');
    for (const body of table.tBodies) {
      body.setAttribute('role', 'rowgroup');
      for (const row of body.rows) {
        row.setAttribute('role', 'row');
        [...row.cells].forEach((cell, index) => {
          cell.setAttribute('role', 'cell');
          if (cell.colSpan === 1) cell.dataset.label = headings[index] || 'Ações';
        });
      }
    }
  };
  const setupTable = table => {
    labelRecords(table);
    if (prepared.has(table)) return;
    prepared.add(table);
    let wrapper = table.parentElement;
    if (!['auto', 'scroll'].includes(getComputedStyle(wrapper).overflowX)) {
      wrapper = document.createElement('div');
      table.before(wrapper);
      wrapper.append(table);
    }
    wrapper.classList.add('table-scroll');
    if (table.matches('[data-mobile-cards]')) wrapper.classList.add('record-list-wrap');
    const hint = document.createElement('p');
    hint.className = 'table-scroll-hint';
    hint.textContent = 'Deslize a tabela para ver todas as colunas →';
    wrapper.before(hint);
    const update = () => {
      const overflow = wrapper.scrollWidth > wrapper.clientWidth + 1;
      hint.classList.toggle('is-visible', overflow);
      if (overflow) {
        wrapper.tabIndex = 0;
        wrapper.setAttribute('role', 'region');
        wrapper.setAttribute('aria-label', 'Tabela com rolagem horizontal');
      } else {
        wrapper.removeAttribute('tabindex');
        wrapper.removeAttribute('role');
        wrapper.removeAttribute('aria-label');
      }
    };
    const observer = new ResizeObserver(update);
    observer.observe(wrapper);
    observer.observe(table);
    update();
  };
  const labelItemRows = () => main.querySelectorAll('.item-editor-table').forEach(table => {
    if (table.querySelector('tr.item-row')) table.classList.add('mobile-item-editor');
    const headers = [...table.querySelectorAll('thead th')].map(th => th.textContent.trim());
    table.querySelectorAll('tr.item-row').forEach(row => [...row.cells].forEach((cell, index) => {
      if (headers[index]) cell.dataset.label = headers[index];
      cell.querySelectorAll('input:not([type=hidden]), select').forEach(input => {
        if (!input.hasAttribute('aria-label') && !input.labels?.length) input.setAttribute('aria-label', headers[index] || 'Item');
      });
      const remove = cell.querySelector('.remove-item-row');
      if (remove) { remove.setAttribute('aria-label', 'Remover item'); remove.textContent = 'Remover'; }
    }));
  });
  main.querySelectorAll('table').forEach(setupTable);
  labelItemRows();
  new MutationObserver(records => {
    let itemsChanged = false;
    records.forEach(record => record.addedNodes.forEach(node => {
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      if (node.matches('table')) setupTable(node);
      node.querySelectorAll('table').forEach(setupTable);
      if (node.matches('.item-row') || node.querySelector('.item-row')) itemsChanged = true;
      const recordTable = node.closest('table[data-mobile-cards]');
      if (recordTable) labelRecords(recordTable);
    }));
    if (itemsChanged) labelItemRows();
  }).observe(main, { childList: true, subtree: true });
})();
