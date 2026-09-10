"""Database-backed job queue for retryable external work."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import click

from .models import AsyncJob, FiscalDocument, db


def enqueue(job_type: str, payload: dict, delay_seconds: int = 0) -> AsyncJob:
    job = AsyncJob(job_type=job_type, payload_json=json.dumps(payload),
                   available_at=datetime.now() + timedelta(seconds=max(delay_seconds, 0)))
    db.session.add(job)
    return job


def _process(job: AsyncJob) -> None:
    payload = json.loads(job.payload_json)
    if job.job_type not in {'FISCAL_EMITIR', 'FISCAL_CONSULTAR'}:
        raise ValueError(f'Tipo de tarefa desconhecido: {job.job_type}')
    from .fiscal import consult_focus_nfe, consult_focus_nfse, get_fiscal_config, issue_with_external_api
    document = db.session.get(FiscalDocument, int(payload['document_id']))
    config = get_fiscal_config()
    if not document or not config:
        raise ValueError('Documento ou configuração fiscal não encontrado.')
    if job.job_type == 'FISCAL_EMITIR':
        issue_with_external_api(document, config)
    elif document.document_type == 'NFSE':
        consult_focus_nfse(document, config)
    else:
        consult_focus_nfe(document, config)


def run_next_job() -> AsyncJob | None:
    query = AsyncJob.query.filter(AsyncJob.status == 'PENDENTE', AsyncJob.available_at <= datetime.now()).order_by(AsyncJob.id)
    if db.session.get_bind().dialect.name == 'mysql':
        query = query.with_for_update(skip_locked=True)
    job = query.first()
    if not job:
        return None
    job.status = 'PROCESSANDO'; job.attempts += 1; db.session.commit()
    try:
        _process(job); job.status = 'CONCLUIDA'; job.last_error = None
    except Exception as exc:
        job.last_error = str(exc)[:4000]
        if job.attempts >= 5:
            job.status = 'FALHOU'
        else:
            job.status = 'PENDENTE'; job.available_at = datetime.now() + timedelta(minutes=2 ** job.attempts)
    db.session.commit()
    return job


def register_job_commands(app):
    @app.cli.command('jobs-worker')
    @click.option('--once', is_flag=True, help='Processa no máximo uma tarefa e encerra.')
    def jobs_worker(once):
        while True:
            job = run_next_job()
            if job:
                click.echo(f'{job.id}: {job.status}')
            if once or not job:
                break
