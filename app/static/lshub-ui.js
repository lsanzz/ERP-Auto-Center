/* Expose the current location without changing navigation behavior. */
document.querySelectorAll('.grouped-nav a').forEach(link => {
  const target = new URL(link.href, location.href);
  const section = url => new URLSearchParams(url.search).get('secao');  // /gestao/ serve o relatório financeiro e o de estoque
  if (target.pathname.replace(/\/$/, '') === location.pathname.replace(/\/$/, '') && section(target) === section(location)) {
    link.setAttribute('aria-current', 'page');
    link.closest('.nav-group')?.classList.add('is-current');
  }
});

/* Mostrar/ocultar saldos (padrão: ocultos), lembrado neste aparelho. */
(() => {
  const root = document.documentElement;
  const KEY = 'lshub-show-money';
  try { root.classList.toggle('show-money', localStorage.getItem(KEY) === '1'); } catch (_) {}
  const sync = () => document.querySelectorAll('[data-money-toggle]').forEach(button => button.setAttribute('aria-pressed', String(root.classList.contains('show-money'))));
  sync();
  document.addEventListener('click', event => {
    if (!event.target.closest('[data-money-toggle]')) return;
    const shown = root.classList.toggle('show-money');
    try { localStorage.setItem(KEY, shown ? '1' : '0'); } catch (_) {}
    sync();
  });
})();
