document.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', () => document.getElementById(button.dataset.open).showModal()));
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('.hub-settle').forEach(form => {
  const update = () => {
    const value = name => Number(form.elements[name].value) || 0;
    const amount = value('valor_baixa') + value('juros') - value('desconto') - value('taxa') + value('acrescimo');
    form.querySelector('output').textContent = amount.toLocaleString('pt-BR', {style:'currency',currency:'BRL'});
  };
  form.addEventListener('input', update);
});
