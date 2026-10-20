(() => {
  const mappingForm = document.getElementById('migration-mapping');
  if (mappingForm) {
    mappingForm.addEventListener('change', (event) => {
      if (event.target.tagName !== 'SELECT') return;
      document.querySelector('[name="confirmed"]').checked = false;
      document.querySelector('button[value="import"]').disabled = true;
      document.querySelector('[data-preview-state]').textContent =
        'As colunas mudaram. Clique em “Atualizar prévia” e confira os novos valores antes de confirmar.';
    });
  }
  const upload = document.querySelector('[data-migration-upload]');
  if (upload) {
    const input = upload.querySelector('[type=file]');
    const feedback = document.getElementById('file-feedback');
    input.addEventListener('change', () => {
      const files = Array.from(input.files);
      const size = files.reduce((sum, file) => sum + file.size, 0);
      const error = files.length > 20 ? 'Selecione no máximo 20 arquivos.' :
        size > 100 * 1024 * 1024 ? 'O envio excede 100 MB. Divida em mais envios.' : '';
      input.setCustomValidity(error);
      feedback.textContent = error || `${files.length} arquivo(s) selecionado(s) · ${(size / 1024 / 1024).toFixed(1)} MB`;
    });
    upload.addEventListener('submit', () => {
      upload.querySelector('button[type=submit]').disabled = true;
      upload.querySelector('[data-upload-status]').textContent = 'Enviando arquivos. Aguarde a confirmação…';
    });
  }
  document.querySelectorAll('[data-history-url]').forEach((row) => {
    const labels = {PREPARANDO: 'Preparando leitura', PREVIA: 'Aguardando revisão',
      IMPORTANDO: 'Importando', CONCLUIDA: 'Concluída', ERRO_LEITURA: 'Falha na leitura',
      ERRO_IMPORTACAO: 'Importação interrompida'};
    async function refresh() {
      if (document.hidden) { window.setTimeout(refresh, 5000); return; }
      try {
        const response = await fetch(row.dataset.historyUrl, {cache: 'no-store', signal: AbortSignal.timeout(15000)});
        if (!response.ok || response.redirected) throw new Error('history');
        const data = await response.json();
        row.querySelector('.mi-badge').textContent = labels[data.status] || data.status;
        row.cells[3].textContent = `${data.imported} / ${data.total}`;
        if (!['PREPARANDO', 'IMPORTANDO'].includes(data.status)) return;
      } catch (_) {
        row.querySelector('.mi-badge').textContent = 'Sem conexão · abra para verificar';
      }
      window.setTimeout(refresh, 5000);
    }
    window.setTimeout(refresh, 2500);
  });
  const run = document.querySelector('[data-poll-url]');
  if (!run) return;
  let failures = 0;
  async function wake() {
    const message = run.querySelector('[data-progress-message]');
    try {
      const response = await fetch(run.dataset.wakeUrl, {
        method: 'POST', headers: {'X-CSRFToken': run.dataset.csrf, 'Accept': 'application/json'},
        signal: AbortSignal.timeout(15000)
      });
      if (!response.ok || response.redirected) throw new Error('wake');
      if (message) message.textContent = 'Processamento acionado. Aguardando leitura da fila…';
    } catch (_) {
      if (message) message.textContent = 'Não foi possível acionar o processamento. Confira a conexão e tente reativar.';
    }
  }
  run.querySelector('[data-wake-worker]')?.addEventListener('click', wake);
  wake();
  async function poll() {
    if (document.hidden) { window.setTimeout(poll, 5000); return; }
    try {
      const response = await fetch(run.dataset.pollUrl, {headers: {'Accept': 'application/json'}, cache: 'no-store', signal: AbortSignal.timeout(15000)});
      if (!response.ok || response.redirected) throw new Error('status');
      const data = await response.json();
      if (data.status !== run.dataset.status) { window.location.reload(); return; }
      for (const key of ['total', 'imported', 'skipped', 'errors']) {
        const counter = run.querySelector(`[data-count="${key}"]`);
        if (counter) counter.textContent = data[key].toLocaleString('pt-BR');
      }
      const message = run.querySelector('[data-progress-message]');
      if (message) message.textContent = data.message || (data.queue_status === 'PENDENTE' ? 'Aguardando início na fila. Se não avançar, clique em Reativar processamento.' : data.status === 'PREPARANDO' ?
        `${data.total.toLocaleString('pt-BR')} registros lidos. Preparando a revisão…` :
        `${data.processed.toLocaleString('pt-BR')} de ${data.total.toLocaleString('pt-BR')} registros processados.`);
      const progress = run.querySelector('progress');
      if (progress && data.status === 'IMPORTANDO') { progress.max = data.total || 1; progress.value = data.processed; }
      failures = 0;
    } catch (_) {
      failures += 1;
      const message = run.querySelector('[data-progress-message]');
      if (message) message.textContent = 'Não foi possível atualizar o progresso. Tentaremos novamente; se persistir, recarregue a página.';
    }
    window.setTimeout(poll, Math.min(30000, 2500 * (failures + 1)));
  }
  window.setTimeout(poll, 2000);
})();
