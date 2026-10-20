import csv
import io
import json
import uuid
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, Response, stream_with_context, url_for
from sqlalchemy import select, update

from ..auth import admin_required, current_user
from ..jobs import enqueue
from ..models import AsyncJob, db
from .worker import start_worker
from .models import DataMigration, MigrationRow
from .service import SCHEMAS, convert, storage_path, resolve_work_orders, resolve_payments

migration_bp = Blueprint('data_migration', __name__, url_prefix='/configuracoes/migracao')
EXTENSIONS = {'.csv', '.tsv', '.txt', '.html', '.htm', '.xls', '.xlsx'}


def get_migration(migration_id, lock=False):
    query = select(DataMigration).where(DataMigration.id == migration_id)
    if lock:
        query = query.with_for_update()
    migration = db.session.scalar(query)
    if not migration:
        abort(404)
    return migration


@migration_bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@migration_bp.get('')
@admin_required
def index():
    page = max(1, request.args.get('page', 1, type=int))
    runs = db.paginate(select(DataMigration).order_by(DataMigration.id.desc()), page=page, per_page=20, error_out=False)
    return render_template('migracao/index.html', runs=runs, schemas=SCHEMAS)


@migration_bp.post('/enviar')
@admin_required
def upload():
    files = [file for file in request.files.getlist('files') if file.filename]
    entity = request.form.get('entity')
    source = request.form.get('source', '').strip()
    try:
        if entity not in SCHEMAS or not source or len(source) > 80:
            raise ValueError('Selecione o destino e informe o sistema de origem (até 80 caracteres).')
        if not 1 <= len(files) <= 20:
            raise ValueError('Selecione de 1 a 20 arquivos do mesmo tipo de cadastro por envio.')
        options = {'encoding': request.form.get('encoding', 'utf-8-sig'),
                   'delimiter': request.form.get('delimiter', 'auto'),
                   'table': int(request.form.get('table', '0')),
                   'header_row': int(request.form.get('header_row', '1'))}
        if options['encoding'] not in ('utf-8-sig', 'cp1252', 'latin-1') or options['delimiter'] not in ('auto', ';', ',', '\t', '|'):
            raise ValueError('Codificação ou separador inválido.')
        if not 0 <= options['table'] <= 100 or not 1 <= options['header_row'] <= 1000:
            raise ValueError('Use 0 para detectar a tabela automaticamente, ou informe um número de 1 a 100.')
        for file in files:
            if Path(file.filename).suffix.lower() not in EXTENSIONS:
                raise ValueError('Formato não suportado. Use CSV, TSV, TXT, HTML, XLS ou XLSX.')
    except (ValueError, TypeError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('.index'))
    saved, runs = [], []
    try:
        for file in files:
            migration = DataMigration(user_id=current_user().id, entity=entity, source=source,
                filename=file.filename.replace('\\', '/').rsplit('/', 1)[-1][:255],
                storage_name=uuid.uuid4().hex + Path(file.filename).suffix.lower(), options_json=json.dumps(options))
            path = storage_path(migration)
            saved.append(path)
            file.save(path)
            if not path.stat().st_size:
                raise ValueError('Há um arquivo vazio no envio. Selecione uma exportação com dados.')
            db.session.add(migration)
            db.session.flush()
            enqueue('MIGRATION_PREPARE', {'migration_id': migration.id})
            runs.append(migration)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        for path in saved:
            path.unlink(missing_ok=True)
        if isinstance(exc, ValueError):
            flash(str(exc), 'error')
            return redirect(url_for('.index'))
        raise
    start_worker(current_app._get_current_object())
    flash(f'{len(runs)} arquivo(s) recebido(s). A leitura será feita em segundo plano.', 'success')
    return redirect(url_for('.detail', migration_id=runs[0].id) if len(runs) == 1 else url_for('.index'))


@migration_bp.route('/<int:migration_id>', methods=['GET', 'POST'])
@admin_required
def detail(migration_id):
    migration = get_migration(migration_id, lock=request.method == 'POST')
    headers = json.loads(migration.headers_json)
    schema = SCHEMAS[migration.entity]
    mapping = json.loads(migration.mapping_json)
    reviewed_mapping = dict(mapping)
    if request.method == 'POST':
        if migration.status != 'PREVIA':
            abort(409)
        try:
            mapping = {field: int(request.form[field]) for field in schema[2] if request.form.get(field, '') != ''}
            if any(index < 0 or index >= len(headers) for index in mapping.values()):
                raise ValueError('Selecione apenas colunas disponíveis no arquivo.')
            if len(set(mapping.values())) != len(mapping):
                raise ValueError('Associe cada coluna do arquivo a apenas um campo de destino.')
            if any(field not in mapping for field in schema[3]):
                raise ValueError('Associe todas as colunas obrigatórias antes de continuar.')
            migration.mapping_json = json.dumps(mapping)
            if request.form.get('action') == 'import':
                if mapping != reviewed_mapping:
                    db.session.commit()
                    flash('As colunas foram alteradas. Confira a prévia atualizada e confirme novamente.', 'warning')
                    return redirect(url_for('.detail', migration_id=migration.id))
                if request.form.get('confirmed') != 'yes':
                    raise ValueError('Confirme a revisão das colunas antes de importar.')
                migration.status = 'IMPORTANDO'
                enqueue('MIGRATION_IMPORT', {'migration_id': migration.id})
            db.session.commit()
            start_worker(current_app._get_current_object())
            return redirect(url_for('.detail', migration_id=migration.id))
        except ValueError as exc:
            flash(str(exc), 'error')
    rows = db.session.execute(select(MigrationRow.__table__).where(MigrationRow.migration_id == migration.id)
        .order_by(MigrationRow.number).limit(20)).mappings().all()
    preview = []
    for row in rows:
        values = json.loads(row['payload'])
        try:
            converted = convert(migration, values, mapping)
            if migration.entity == 'ordens_servico' and 'status_origem' in mapping:
                converted['status_origem'] = converted['status']
            error = None
        except ValueError as exc:
            converted, error = {}, str(exc)
        preview.append({'number': row['number'], 'values': values, 'converted': converted, 'error': error})
    candidates = [(item['number'], dict(item['converted']), '') for item in preview if not item['error']]
    validation = []
    if migration.entity == 'ordens_servico':
        candidates = resolve_work_orders(candidates, validation, (None, 'Cliente VHSys (Importado)'))
    candidates = resolve_payments(candidates, validation)
    resolved = {number: data for number, data, _ in candidates}
    errors = {number: message for number, _, message in validation}
    for item in preview:
        item['converted'].update(resolved.get(item['number'], {}))
        item['error'] = item['error'] or errors.get(item['number'])
    return render_template('migracao/detail.html', migration=migration, headers=headers, schema=schema,
        mapping=mapping, preview=preview, processed=migration.imported + migration.skipped + migration.errors)


@migration_bp.get('/<int:migration_id>/status')
@admin_required
def status(migration_id):
    migration = get_migration(migration_id)
    job = db.session.scalar(select(AsyncJob).where(
        AsyncJob.job_type.in_(('MIGRATION_PREPARE', 'MIGRATION_IMPORT')),
        AsyncJob.payload_json == json.dumps({'migration_id': migration_id})
    ).order_by(AsyncJob.id.desc()).limit(1))
    return jsonify(status=migration.status, total=migration.total, imported=migration.imported,
                   queue_status=job.status if job else None, message=migration.last_error,
                   skipped=migration.skipped, errors=migration.errors,
                   processed=migration.imported + migration.skipped + migration.errors)


@migration_bp.post('/processar')
@admin_required
def wake_worker():
    start_worker(current_app._get_current_object())
    return jsonify(ok=True)


@migration_bp.post('/<int:migration_id>/retomar')
@admin_required
def retry(migration_id):
    migration = get_migration(migration_id, lock=True)
    if migration.status not in ('ERRO_IMPORTACAO', 'ERRO_LEITURA'):
        abort(409)
    reading = migration.status == 'ERRO_LEITURA'
    migration.status = 'PREPARANDO' if reading else 'IMPORTANDO'
    migration.last_error = None
    enqueue('MIGRATION_PREPARE' if reading else 'MIGRATION_IMPORT', {'migration_id': migration.id})
    db.session.commit()
    start_worker(current_app._get_current_object())
    return redirect(url_for('.detail', migration_id=migration.id))


@migration_bp.post('/<int:migration_id>/retomar-erros')
@admin_required
def retry_errors(migration_id):
    migration = get_migration(migration_id, lock=True)
    if migration.status != 'CONCLUIDA' or not migration.errors:
        abort(409)
    changed = db.session.execute(update(MigrationRow).where(
        MigrationRow.migration_id == migration.id, MigrationRow.result == 'ERRO'
    ).values(result='PENDENTE', message=None)).rowcount
    migration.errors = max(0, migration.errors - changed)
    migration.status = 'IMPORTANDO'
    migration.last_error = None
    enqueue('MIGRATION_IMPORT', {'migration_id': migration.id})
    db.session.commit()
    start_worker(current_app._get_current_object())
    flash(f'{changed} linha(s) com erro foram reenviadas para processamento.', 'success')
    return redirect(url_for('.detail', migration_id=migration.id))


def safe_csv(value):
    value = str(value or '')
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


@migration_bp.get('/<int:migration_id>/relatorio.csv')
@admin_required
def report(migration_id):
    migration = get_migration(migration_id)
    headers = json.loads(migration.headers_json)

    @stream_with_context
    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=';')
        yield '\ufeff'
        writer.writerow(['Registro', 'Resultado', 'Motivo', *map(safe_csv, headers)])
        yield buffer.getvalue()
        after = 0
        while True:
            rows = db.session.execute(select(MigrationRow.__table__).where(MigrationRow.migration_id == migration_id,
                MigrationRow.number > after).order_by(MigrationRow.number).limit(500)).mappings().all()
            if not rows:
                break
            buffer.seek(0)
            buffer.truncate(0)
            for row in rows:
                writer.writerow([row['number'], row['result'], safe_csv(row['message']),
                                 *map(safe_csv, json.loads(row['payload']))])
            after = rows[-1]['number']
            yield buffer.getvalue()
    return Response(generate(), mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename=migracao-{migration_id}.csv'})


@migration_bp.get('/modelo/<entity>.csv')
@admin_required
def template(entity):
    if entity not in SCHEMAS:
        abort(404)
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=';').writerow(SCHEMAS[entity][2].keys())
    return Response('\ufeff' + buffer.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename=modelo-{entity}.csv'})


def configure_upload_limit(app):
    # Must precede CSRF's multipart parsing. Other routes retain the 12 MB limit.
    @app.before_request
    def migration_upload_limit():
        if request.endpoint == 'data_migration.upload':
            request.max_content_length = current_app.config.get('MIGRATION_MAX_UPLOAD_BYTES', 100 * 1024 * 1024)
