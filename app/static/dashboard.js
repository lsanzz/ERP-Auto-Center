// Contadores do painel: sobem de 0 até o valor quando o cartão aparece na tela.
(() => {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const money = new Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL'});
  const whole = new Intl.NumberFormat('pt-BR');
  const run = el => {
    const target = Number(el.dataset.count);
    if (!Number.isFinite(target) || target === 0) return;
    const fmt = el.hasAttribute('data-money') ? money.format : value => whole.format(Math.round(value));
    const start = performance.now();
    const step = now => {
      const t = Math.min((now - start) / 900, 1);
      el.textContent = fmt(target * (1 - Math.pow(1 - t, 3)));
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  const io = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) { run(entry.target); io.unobserve(entry.target); }
  }));
  document.querySelectorAll('[data-count]').forEach(el => io.observe(el));
})();
