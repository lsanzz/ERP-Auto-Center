// Painel do pátio: arrastar o carro pela alça entre Aguardando, Em andamento e Atendida.
// Pointer Events cobrem mouse e toque; o servidor decide a etapa e o status (POST /agenda/patio/<id>/coluna).
(() => {
  const root = document.querySelector('.pk');
  if (!root) return;
  const moveUrl = id => root.dataset.moveUrl.replace(/\/0\/coluna$/, `/${id}/coluna`);
  let drag = null;

  const toast = (text, error) => {
    const el = Object.assign(document.createElement('div'), {className: `pk-toast${error ? ' err' : ''}`, textContent: text});
    document.body.append(el);
    setTimeout(() => el.remove(), 2600);
  };
  const recount = () => root.querySelectorAll('.pk-col').forEach(col => {
    col.querySelector('.pk-count').textContent = col.querySelectorAll('.pk-card:not(.pk-ghost)').length;
  });
  const columnAt = (x, y) => document.elementsFromPoint(x, y).map(el => el.closest('.pk-col')).find(Boolean);

  root.addEventListener('pointerdown', event => {
    const grip = event.target.closest('.pk-grip');
    if (!grip || event.button > 0) return;
    const card = grip.closest('.pk-card');
    const rect = card.getBoundingClientRect();
    const ghost = card.cloneNode(true);
    ghost.classList.add('pk-ghost');
    Object.assign(ghost.style, {width: `${rect.width}px`, left: `${rect.left}px`, top: `${rect.top}px`});
    document.body.append(ghost);
    card.classList.add('is-placeholder');
    document.body.classList.add('pk-dragging');
    drag = {card, ghost, from: card.closest('.pk-col'), dx: event.clientX - rect.left, dy: event.clientY - rect.top, over: null, y: event.clientY};
    grip.setPointerCapture(event.pointerId);
    event.preventDefault();
    // No celular as colunas ficam empilhadas: rola a página quando o dedo chega perto da borda.
    const edge = () => {
      if (!drag) return;
      const speed = drag.y < 80 ? -14 : drag.y > innerHeight - 80 ? 14 : 0;
      if (speed) scrollBy(0, speed);
      requestAnimationFrame(edge);
    };
    requestAnimationFrame(edge);
  });

  root.addEventListener('pointermove', event => {
    if (!drag) return;
    drag.ghost.style.left = `${event.clientX - drag.dx}px`;
    drag.ghost.style.top = `${event.clientY - drag.dy}px`;
    drag.y = event.clientY;
    const over = columnAt(event.clientX, event.clientY);
    if (over !== drag.over) {
      drag.over?.classList.remove('is-over');
      over?.classList.add('is-over');
      drag.over = over;
    }
  });

  const finish = async event => {
    if (!drag) return;
    const {card, ghost, from} = drag;
    const target = columnAt(event.clientX, event.clientY) || from;
    drag.over?.classList.remove('is-over');
    ghost.remove();
    card.classList.remove('is-placeholder');
    document.body.classList.remove('pk-dragging');
    drag = null;
    if (target === from) return;
    // Move já na tela e confirma no servidor; se falhar, volta o cartão.
    target.querySelector('[data-list]').prepend(card);
    card.classList.add('is-saving');
    recount();
    try {
      const response = await fetch(moveUrl(card.dataset.id), {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': root.dataset.csrf},
        body: JSON.stringify({coluna: target.dataset.column}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.erro || 'Não foi possível mover.');
      card.classList.remove('is-saving');
      toast(`Movido para ${target.querySelector('h2').textContent}`);
      // A coluna Atendida tem o botão Entregar; recarrega para mostrar os botões certos.
      if (target.dataset.column === 'atendida' || from.dataset.column === 'atendida') setTimeout(() => location.reload(), 700);
    } catch (error) {
      from.querySelector('[data-list]').prepend(card);
      card.classList.remove('is-saving');
      recount();
      toast(error.message, true);
    }
  };
  root.addEventListener('pointerup', finish);
  root.addEventListener('pointercancel', finish);
})();
