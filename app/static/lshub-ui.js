/* Expose the current location without changing navigation behavior. */
document.querySelectorAll('.grouped-nav a').forEach(link => {
  const target = new URL(link.href, location.href);
  const section = url => new URLSearchParams(url.search).get('secao');  // /gestao/ serve o relatório financeiro e o de estoque
  if (target.pathname.replace(/\/$/, '') === location.pathname.replace(/\/$/, '') && section(target) === section(location)) {
    link.setAttribute('aria-current', 'page');
    link.closest('.nav-group')?.classList.add('is-current');
  }
});

/* Mostrar/ocultar saldos por conta/grupo (padrão: ocultos), lembrado neste aparelho. */
(() => {
  const KEY = 'lshub-saldos-visiveis';
  let shown;
  try { shown = new Set(JSON.parse(localStorage.getItem(KEY) || '[]')); } catch (_) { shown = new Set(); }
  const apply = () => {
    document.querySelectorAll('[data-private][data-key]').forEach(el => el.classList.toggle('is-shown', shown.has(el.dataset.key)));
    document.querySelectorAll('[data-privacy-toggle]').forEach(button => button.setAttribute('aria-pressed', String(shown.has(button.dataset.privacyToggle))));
  };
  apply();
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-privacy-toggle]');
    if (!button) return;
    event.preventDefault();  // o olho fica dentro de cartões que são links
    const key = button.dataset.privacyToggle;
    if (shown.has(key)) shown.delete(key); else shown.add(key);
    try { localStorage.setItem(KEY, JSON.stringify([...shown])); } catch (_) {}
    apply();
  });
})();
