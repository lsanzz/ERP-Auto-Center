// Landing LS Hub. Escreve só variáveis CSS e classes (a CSP proíbe estilo inline em atributos,
// mas permite element.style.setProperty). Sem JS ou com movimento reduzido, tudo fica visível.
const root = document.documentElement;
root.classList.add('js');
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const clamp = (value) => Math.min(1, Math.max(0, value));
window.addEventListener('load', () => requestAnimationFrame(() => root.classList.add('is-loaded')));
if (document.readyState === 'complete') root.classList.add('is-loaded');
setTimeout(() => root.classList.add('is-loaded'), 1200); // título nunca fica escondido se o load atrasar

// Frase revelada palavra a palavra.
const statement = document.querySelector('[data-words]');
let words = [];
if (statement) {
  const text = statement.textContent.trim();
  statement.textContent = '';
  words = text.split(/\s+/).map((word) => {
    const span = document.createElement('span');
    span.className = 'w' + (/^(LS|Hub)/.test(word) ? ' accent' : '');
    span.textContent = word + ' ';
    statement.appendChild(span);
    return span;
  });
  if (reduced) words.forEach((w) => w.classList.add('lit'));
}

// Progresso de rolagem (--p) de cada seção: fixas usam o trecho percorrido; as demais, entrada até saída.
const header = document.querySelector('.header');
const tracked = [...document.querySelectorAll('[data-sticky], [data-scroll]')];
const update = () => {
  const vh = window.innerHeight;
  header && header.classList.toggle('is-scrolled', window.scrollY > 10);
  if (reduced) return;
  tracked.forEach((el) => {
    const rect = el.getBoundingClientRect();
    if (rect.bottom < -vh || rect.top > vh * 2) return;
    const span = el.offsetHeight - vh;
    const p = el.hasAttribute('data-sticky') && span > 40 ? clamp(-rect.top / span) : clamp((vh - rect.top) / (vh + rect.height));
    el.style.setProperty('--p', p.toFixed(4));
    if (el.contains(statement) && words.length) {
      const lit = Math.round(clamp(p * 1.25) * words.length);
      words.forEach((w, i) => w.classList.toggle('lit', i < lit));
    }
  });
};
let ticking = false;
const onScroll = () => {
  if (ticking) return;
  ticking = true;
  requestAnimationFrame(() => { update(); ticking = false; });
};
window.addEventListener('scroll', onScroll, { passive: true });
window.addEventListener('resize', onScroll);
update();

// Profundidade com o mouse no hero e na tela do tour.
if (!reduced && window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
  [document.querySelector('.hero'), document.querySelector('.tour-stage')].filter(Boolean).forEach((zone) => {
    let frame = 0;
    zone.addEventListener('pointermove', (event) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const rect = zone.getBoundingClientRect();
        zone.style.setProperty('--mx', (((event.clientX - rect.left) / rect.width) * 2 - 1).toFixed(3));
        zone.style.setProperty('--my', (((event.clientY - rect.top) / rect.height) * 2 - 1).toFixed(3));
      });
    });
    zone.addEventListener('pointerleave', () => { zone.style.setProperty('--mx', 0); zone.style.setProperty('--my', 0); });
  });
}

// Tour: o passo no centro da tela escolhe a tela mostrada no aparelho.
const steps = [...document.querySelectorAll('.step')];
const screens = [...document.querySelectorAll('.dscreen')];
if (steps.length && 'IntersectionObserver' in window) {
  let current = 0;
  const show = (index) => {
    if (index === current) return;
    screens.forEach((s) => s.classList.remove('was-active'));
    screens[current] && screens[current].classList.add('was-active');
    steps.forEach((s, i) => s.classList.toggle('is-active', i === index));
    screens.forEach((s, i) => s.classList.toggle('is-active', i === index));
    current = index;
  };
  const stepObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => { if (entry.isIntersecting) show(Number(entry.target.dataset.step)); });
  }, { rootMargin: '-45% 0px -45% 0px' });
  steps.forEach((s) => stepObserver.observe(s));
}

// Revelação em cascata.
const revealables = document.querySelectorAll('.reveal');
if (!reduced && 'IntersectionObserver' in window) {
  revealables.forEach((el) => {
    const index = [...el.parentElement.children].filter((c) => c.classList.contains('reveal')).indexOf(el);
    el.style.setProperty('--d', `${(index % 6) * 80}ms`);
  });
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => { if (entry.isIntersecting) { entry.target.classList.add('in'); observer.unobserve(entry.target); } });
  }, { threshold: 0.15, rootMargin: '0px 0px -5% 0px' });
  revealables.forEach((el) => observer.observe(el));
} else {
  revealables.forEach((el) => el.classList.add('in'));
}

// Menu do celular.
const menu = document.querySelector('.menu-toggle');
const navigation = document.querySelector('#main-nav');
if (menu && navigation) {
  const setOpen = (open) => { menu.setAttribute('aria-expanded', String(open)); navigation.classList.toggle('is-open', open); };
  menu.addEventListener('click', () => setOpen(menu.getAttribute('aria-expanded') !== 'true'));
  navigation.addEventListener('click', (event) => { if (event.target.closest('a')) setOpen(false); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && menu.getAttribute('aria-expanded') === 'true') { setOpen(false); menu.focus(); } });
}

// "Escolher plano" já seleciona o plano no formulário.
document.querySelectorAll('[data-plan]').forEach((link) => {
  link.addEventListener('click', () => { const select = document.querySelector('#plan'); if (select) select.value = link.dataset.plan; });
});

const errorSummary = document.querySelector('#form-errors');
if (errorSummary) errorSummary.focus();

// Evita envio duplicado.
const form = document.querySelector('.lead-form');
if (form) {
  const button = form.querySelector('[type=submit]');
  const label = button.textContent;
  form.addEventListener('submit', () => { button.disabled = true; button.textContent = 'Enviando…'; });
  window.addEventListener('pageshow', () => { button.disabled = false; button.textContent = label; });
}
