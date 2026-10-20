"""Database-backed job queue for retryable external work."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import click
from sqlalchemy import update

from .models import AsyncJob, FiscalDocument, db


def enqueue(job_type: str, payload: dict, delay_seconds: int = 0) -> AsyncJob:
    job = AsyncJob(job_type=job_type, payload_json=json.dumps(payload),
                   available_at=datetime.now() + timedelta(seconds=max(delay_seconds, 0)))
    db.session.add(job)
    return job


def _process(job: AsyncJob) -> None:
    payload = json.loads(job.payload_json)
    if job.job_type in {'MIGRATION_PREPARE', 'MIGRATION_IMPORT'}:
        from .data_migration.service import prepare, import_batch
        handler = prepare if job.job_type == 'MIGRATION_PREPARE' else import_batch
        handler(int(payload['migration_id']))
        return
    if job.job_type not in {'FISCAL_EMITIR', 'FISCAL_CONSULTAR'}:
        raise ValueError(f'Tipo de tarefa desconhecido: {job.job_type}')
    from .fiscal import consult_focus_nfe, consult_focus_nfse, get_fiscal_config, issue_with_external_api
    document = db.session.get(FiscalDocument, int(payload['document_id']))
    config = get_fiscal_config()
    if not document or not config:
        raise ValueError('Documento ou configuração fiscal não encontrado.')
    if job.job_type == 'FISCAL_EMITIR':
        issue_with_external_api(document, config)
    elif document.provider_name == 'UNINFE':
        from .uninfe_dispatch import consult
        consult(document)
    elif document.document_type == 'NFSE':
        consult_focus_nfse(document, config)
    else:
        consult_focus_nfe(document, config)


def run_next_job(job_types=None) -> AsyncJob | None:
    query = AsyncJob.query.filter(AsyncJob.status == 'PENDENTE', AsyncJob.available_at <= datetime.now()).order_by(AsyncJob.id)
    if job_types:
        query = query.filter(AsyncJob.job_type.in_(job_types))
    if db.session.get_bind().dialect.name == 'mysql':
        query = query.with_for_update(skip_locked=True)
    job = query.first()
    if not job:
        # End the transaction even when idle: release MySQL locks and discard an old
        # repeatable-read snapshot before the next polling iteration.
        db.session.rollback()
        return None
    claimed = db.session.execute(update(AsyncJob).where(
        AsyncJob.id == job.id, AsyncJob.status == 'PENDENTE'
    ).values(status='PROCESSANDO', attempts=AsyncJob.attempts + 1))
    if claimed.rowcount != 1:
        db.session.rollback()
        return None
    db.session.commit()
    job_id = job.id
    try:
        _process(job); job.status = 'CONCLUIDA'; job.last_error = None
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        job = db.session.get(AsyncJob, job_id)
        job.last_error = str(exc)[:4000]
        is_migration = job.job_type.startswith('MIGRATION_')
        if job.attempts >= 5 or (is_migration and isinstance(exc, ValueError)):
            job.status = 'FALHOU'
            if is_migration:
                from .data_migration.models import DataMigration
                migration = db.session.get(DataMigration, json.loads(job.payload_json)['migration_id'])
                if migration:
                    migration.status = 'ERRO_LEITURA' if job.job_type == 'MIGRATION_PREPARE' else 'ERRO_IMPORTACAO'
                    migration.last_error = (str(exc)[:500] if isinstance(exc, ValueError) else
                        'Não foi possível concluir o processamento. Consulte o administrador e os logs da fila.')
        else:
            job.status = 'PENDENTE'; job.available_at = datetime.now() + timedelta(minutes=2 ** job.attempts)
            if is_migration:
                from .data_migration.models import DataMigration
                migration = db.session.get(DataMigration, json.loads(job.payload_json)['migration_id'])
                if migration:
                    migration.last_error = 'Falha temporária no processamento. Uma nova tentativa foi agendada.'
    db.session.commit()
    return job


def register_job_commands(app):
    @app.cli.command('jobs-worker')
    @click.option('--once', is_flag=True, help='Processa no máximo uma tarefa e encerra.')
    @click.option('--watch', is_flag=True, help='Continua aguardando novas tarefas quando a fila está vazia.')
    @click.option('--poll-interval', type=click.IntRange(1, 60), default=3, show_default=True)
    def jobs_worker(once, watch, poll_interval):
        if watch:
            click.echo('Processador ativo. Aguardando tarefas; use Ctrl+C para encerrar.')
        while True:
            try:
                job = run_next_job()
                if job:
                    click.echo(f'{job.id}: {job.status}')
                    if job.last_error:
                        click.echo('A tarefa encontrou um erro. Consulte o resultado na tela de migração.')
            finally:
                db.session.remove()
            if once or (not job and not watch):
                break
            if not job:
                time.sleep(poll_interval)
