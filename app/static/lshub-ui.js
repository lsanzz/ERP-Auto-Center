/* Expose the current location without changing navigation behavior. */
document.querySelectorAll('.grouped-nav a').forEach(link => {
  const target = new URL(link.href, location.href);
  if (target.pathname.replace(/\/$/, '') === location.pathname.replace(/\/$/, '')) {
    link.setAttribute('aria-current', 'page');
    link.closest('.nav-group')?.classList.add('is-current');
  }
});
