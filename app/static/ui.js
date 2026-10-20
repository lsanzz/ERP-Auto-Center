// Interações do design system: toasts, modal de confirmação, onda de clique e trava de duplo envio.
(() => {
  const DANGER = /excluir|apagar|estornar|inativar|remover/i;
  const ICON = { success: '✓', error: '!', warning: '!', info: 'i' };

  // Toasts a partir das mensagens flash renderizadas pelo servidor.
  function toast(message, category = 'info') {
    let stack = document.querySelector('.ui-toasts');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'ui-toasts';
      stack.setAttribute('aria-live', 'polite');
      document.body.appendChild(stack);
    }
    const kind = ICON[category] ? category : 'info';
    const item = document.createElement('div');
    item.className = `ui-toast ${kind}`;
    item.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    const icon = document.createElement('span'); icon.className = 'ui-toast-icon'; icon.textContent = ICON[kind]; icon.setAttribute('aria-hidden', 'true');
    const text = document.createElement('div'); text.textContent = message;
    const close = document.createElement('button'); close.type = 'button'; close.className = 'ui-toast-close'; close.setAttribute('aria-label', 'Fechar aviso'); close.textContent = '×';
    item.append(icon, text, close);
    // Erros ficam até o usuário fechar; os demais somem sozinhos.
    const duration = kind === 'error' ? 0 : 5000;
    let timer;
    const dismiss = () => { clearTimeout(timer); item.classList.add('leaving'); setTimeout(() => item.remove(), 260); };
    close.addEventListener('click', dismiss);
    if (duration) {
      const bar = document.createElement('span'); bar.className = 'ui-toast-bar'; bar.style.animationDuration = `${duration}ms`;
      item.appendChild(bar);
      let remaining = duration, started = Date.now();
      const schedule = () => { started = Date.now(); timer = setTimeout(dismiss, remaining); };
      item.addEventListener('mouseenter', () => { clearTimeout(timer); remaining -= Date.now() - started; });
      item.addEventListener('mouseleave', schedule);
      schedule();
    }
    stack.appendChild(item);
  }

  function flashesToToasts() {
    document.querySelectorAll('.flash-list').forEach((list) => {
      list.querySelectorAll('.flash').forEach((flash) => {
        const category = ['success', 'error', 'warning'].find((name) => flash.classList.contains(name)) || 'info';
        toast(flash.textContent.trim(), category);
      });
      list.remove();
    });
  }

  // Modal de confirmação no lugar do confirm() nativo.
  let dialog;
  function buildDialog() {
    dialog = document.createElement('dialog');
    dialog.className = 'ui-dialog';
    dialog.setAttribute('aria-labelledby', 'ui-dialog-title');
    dialog.innerHTML = `
      <form method="dialog">
        <div class="ui-dialog-body">
          <span class="ui-dialog-icon" aria-hidden="true">!</span>
          <h2 class="ui-dialog-title" id="ui-dialog-title"></h2>
          <p class="ui-dialog-text"></p>
        </div>
        <div class="ui-dialog-actions">
          <button value="cancel" class="outline">Cancelar</button>
          <button value="ok" class="ui-dialog-confirm">Confirmar</button>
        </div>
      </form>`;
    document.body.appendChild(dialog);
  }

  function ask(message) {
    if (!dialog) buildDialog();
    const danger = DANGER.test(message);
    dialog.classList.toggle('is-danger', danger);
    dialog.querySelector('.ui-dialog-title').textContent = danger ? 'Confirmar exclusão ou estorno' : 'Confirmar ação';
    dialog.querySelector('.ui-dialog-text').textContent = message;
    dialog.querySelector('.ui-dialog-confirm').textContent = danger ? 'Sim, continuar' : 'Confirmar';
    dialog.returnValue = '';
    dialog.showModal();
    dialog.querySelector('[value=cancel]').focus();
    return new Promise((resolve) => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'ok'), { once: true }));
  }

  function upgradeInlineConfirms() {
    document.querySelectorAll('form[onsubmit*="confirm("]').forEach((form) => {
      const match = form.getAttribute('onsubmit').match(/confirm\((['"])([\s\S]*?)\1\)/);
      if (!match) return;
      form.dataset.confirm = match[2];
      form.removeAttribute('onsubmit');
    });
  }

  document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method === 'dialog') return;
    if (form.dataset.confirm && form.dataset.confirmed !== 'yes') {
      event.preventDefault();
      const submitter = event.submitter;
      if (await ask(form.dataset.confirm)) {
        form.dataset.confirmed = 'yes';
        form.requestSubmit(submitter && submitter.form === form ? submitter : undefined);
      }
      return;
    }
    if (form.target === '_blank' || form.hasAttribute('data-no-lock')) return;
    // Trava o botão depois do envio para não gerar lançamento/OS em dobro. Espera os outros
    // handlers: formulários enviados por fetch chamam preventDefault e não devem travar.
    const button = event.submitter || form.querySelector('button[type=submit], button:not([type])');
    setTimeout(() => {
      form.dataset.confirmed = '';
      if (event.defaultPrevented || !button) return;
      button.classList.add('is-loading'); button.setAttribute('aria-disabled', 'true');
      setTimeout(() => { button.classList.remove('is-loading'); button.removeAttribute('aria-disabled'); }, 8000);
    }, 0);
  }, true);

  // Ao voltar pelo histórico, a página sai do cache com os botões ainda travados.
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('.is-loading').forEach((el) => { el.classList.remove('is-loading'); el.removeAttribute('aria-disabled'); });
  });

  document.addEventListener('pointerdown', (event) => {
    const target = event.target.closest('button, .button');
    if (!target || target.disabled || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const rect = target.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const box = document.createElement('span');
    box.className = 'ui-ripple-box';
    const ripple = document.createElement('span');
    ripple.className = 'ui-ripple';
    ripple.style.cssText = `width:${size}px;height:${size}px;left:${event.clientX - rect.left - size / 2}px;top:${event.clientY - rect.top - size / 2}px`;
    box.appendChild(ripple);
    target.appendChild(box);
    ripple.addEventListener('animationend', () => box.remove());
  });

  window.lshubToast = toast;
  window.lshubConfirm = ask;
  const start = () => {
    flashesToToasts(); upgradeInlineConfirms();
    // Liga as transições só depois do primeiro quadro com o tema aplicado (ver design-system.css).
    requestAnimationFrame(() => requestAnimationFrame(() => document.documentElement.classList.add('ui-ready')));
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
