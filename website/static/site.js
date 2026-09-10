document.documentElement.classList.add('js-ready');

// Reveal sections with a visible but restrained stagger. Content stays readable
// when JavaScript is unavailable and motion is removed when the visitor asks for it.
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
if ('IntersectionObserver' in window && !reducedMotion.matches) {
  const revealTargets = document.querySelectorAll(
    '.problem-grid, .section-heading, .feature-row, .workflow, .workflow-callout, ' +
    '.plan-card, .onboarding-grid>div, .onboarding-list li, .faq-grid>div, ' +
    '.faq-list details, .contact-copy, .lead-form'
  );

  revealTargets.forEach((element, index) => {
    element.classList.add('reveal-target');
    const groupIndex = element.matches('.plan-card, .workflow li, .onboarding-list li, .faq-list details')
      ? index % 4
      : 0;
    element.style.setProperty('--reveal-delay', `${groupIndex * 80}ms`);
  });

  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.14, rootMargin: '0px 0px -6% 0px' });

  revealTargets.forEach((element) => revealObserver.observe(element));
  reducedMotion.addEventListener('change', (event) => {
    if (event.matches) {
      revealObserver.disconnect();
      revealTargets.forEach((element) => element.classList.add('is-visible'));
    }
  });
}

const menu = document.querySelector('.menu-toggle');
const navigation = document.querySelector('#main-nav');
if (menu && navigation) {
  const closeMenu = () => {
    menu.setAttribute('aria-expanded', 'false');
    navigation.classList.remove('is-open');
  };
  menu.addEventListener('click', () => {
    const expanded = menu.getAttribute('aria-expanded') !== 'true';
    menu.setAttribute('aria-expanded', String(expanded));
    navigation.classList.toggle('is-open', expanded);
  });
  navigation.addEventListener('click', (event) => {
    if (event.target.closest('a')) closeMenu();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && menu.getAttribute('aria-expanded') === 'true') {
      closeMenu();
      menu.focus();
    }
  });
}

document.querySelectorAll('[data-plan]').forEach((link) => {
  link.addEventListener('click', () => {
    const select = document.querySelector('#plan');
    if (select) select.value = link.dataset.plan;
  });
});

const errorSummary = document.querySelector('#form-errors');
if (errorSummary) errorSummary.focus();

const form = document.querySelector('.lead-form');
if (form) {
  form.addEventListener('submit', () => {
    const button = form.querySelector('[type="submit"]');
    button.disabled = true;
    button.textContent = 'Enviando sua solicitação…';
  });
  window.addEventListener('pageshow', () => {
    const button = form.querySelector('[type="submit"]');
    button.disabled = false;
    button.textContent = 'Solicitar minha demonstração ↗';
  });
}
