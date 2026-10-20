// Entrada de mercadoria: linhas de peças, custo sugerido pelo último custo e total da compra.
(() => {
  const form = document.querySelector('#stock-entry form');
  if (!form) return;
  const rows = form.querySelector('[data-stock-rows]');
  const template = rows.querySelector('[data-stock-row]').cloneNode(true);
  const options = document.getElementById('product-options');
  const money = value => value.toLocaleString('pt-BR', {style: 'currency', currency: 'BRL'});
  const update = () => {
    let total = 0;
    rows.querySelectorAll('[data-stock-row]').forEach(row => {
      total += (Number(row.querySelector('[name="quantidade"]').value) || 0) * (Number(row.querySelector('[name="custo"]').value) || 0);
    });
    form.querySelector('[data-stock-total]').textContent = money(total);
  };
  form.querySelector('[data-add-row]').addEventListener('click', () => {
    const row = template.cloneNode(true);
    row.querySelectorAll('input').forEach(input => { input.value = input.name === 'quantidade' ? '1' : ''; });
    rows.append(row);
    row.querySelector('[name="produto"]').focus();
  });
  rows.addEventListener('click', event => {
    if (!event.target.matches('[data-remove-row]') || rows.children.length === 1) return;
    event.target.closest('[data-stock-row]').remove();
    update();
  });
  rows.addEventListener('change', event => {
    if (event.target.name !== 'produto') return;
    const option = [...options.options].find(item => item.value === event.target.value);
    const cost = event.target.closest('[data-stock-row]').querySelector('[name="custo"]');
    if (option && !cost.value) cost.value = Number(option.dataset.cost || 0).toFixed(2);
    update();
  });
  form.addEventListener('input', update);
  if (location.hash === '#lancar') form.closest('dialog').showModal();
})();
