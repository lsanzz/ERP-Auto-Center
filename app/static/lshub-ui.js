/* Expose the current location without changing navigation behavior. */
document.querySelectorAll('.grouped-nav a').forEach(link => {
  const target = new URL(link.href, location.href);
  const section = url => new URLSearchParams(url.search).get('secao');  // /gestao/ serve o relatório financeiro e o de estoque
  if (target.pathname.replace(/\/$/, '') === location.pathname.replace(/\/$/, '') && section(target) === section(location)) {
    link.setAttribute('aria-current', 'page');
    link.closest('.nav-group')?.classList.add('is-current');
  }
});
