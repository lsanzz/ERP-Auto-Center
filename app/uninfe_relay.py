"""Outbound-only Windows bridge API, scoped to this installation's company."""
from datetime import datetime
import hashlib
import hmac
import re

from flask import Blueprint, abort, current_app, jsonify, request
from defusedxml import ElementTree as ET
from .models import FiscalDocument, UniNFeSubmission, UniNFeRelayTask, db
from .uninfe_transport import MAX_XML_BYTES, NS, apply_protocol

relay_bp = Blueprint('uninfe_relay', __name__, url_prefix='/api/uninfe-connector')


def credentials():
    identity = current_app.config.get('UNINFE_CONNECTOR_ID', '')
    token = current_app.config.get('UNINFE_CONNECTOR_TOKEN', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', identity) or len(token) < 32:
        raise ValueError('Configure a identificação e uma credencial forte do conector Windows na hospedagem.')
    return identity, token


def enqueue_invoice(document, submission):
    identity, _ = credentials()
    task = db.session.get(UniNFeRelayTask, submission.id)
    if task is None:
        db.session.add(UniNFeRelayTask(submission_id=submission.id, connector_id=identity))
        document.status = 'AGUARDANDO_CONECTOR'


@relay_bp.before_request
def authenticate():
    # TLS must terminate at the trusted reverse proxy configured for the ERP.
    if not request.is_secure and not current_app.testing:
        abort(403)
    try:
        identity, token = credentials()
    except ValueError:
        abort(503)
    supplied = request.headers.get('Authorization', '')
    if (not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode())
            or not hmac.compare_digest(request.headers.get('X-Connector-ID', '').encode(), identity.encode())):
        abort(401)


@relay_bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def task_rows(task_id):
    identity, _ = credentials()
    task = (UniNFeRelayTask.query.filter_by(submission_id=task_id, connector_id=identity)
            .with_for_update().populate_existing().first())
    if task is None:
        abort(404)
    submission = db.session.get(UniNFeSubmission, task_id)
    document = (FiscalDocument.query.filter_by(id=submission.document_id)
                .with_for_update().populate_existing().one())
    if (document.provider_name != 'UNINFE' or submission.environment != 'HOMOLOGACAO'
            or document.environment != submission.environment
            or document.access_key != submission.access_key):
        abort(409)
    return task, submission, document


@relay_bp.get('/tasks')
def list_tasks():
    identity, _ = credentials()
    after = request.args.get('after', 0, type=int)
    tasks = (UniNFeRelayTask.query.filter(UniNFeRelayTask.connector_id == identity,
             UniNFeRelayTask.status != 'DONE', UniNFeRelayTask.submission_id > after)
             .order_by(UniNFeRelayTask.submission_id).limit(20).all())
    return jsonify(tasks=[task.submission_id for task in tasks])


@relay_bp.get('/tasks/<int:task_id>')
def get_task(task_id):
    task, submission, document = task_rows(task_id)
    if hashlib.sha256(submission.prepared_xml.encode()).hexdigest() != submission.xml_sha256:
        abort(409)
    return jsonify(id=task_id, status=task.status, key=submission.access_key,
                   environment=submission.environment, model=submission.model,
                   xml=submission.prepared_xml, sha256=submission.xml_sha256)


@relay_bp.post('/tasks/<int:task_id>/start')
def start_task(task_id):
    task, submission, document = task_rows(task_id)
    # The atomic conditional update is also required on SQLite (no row locks).
    changed = db.session.query(UniNFeRelayTask).filter_by(
        submission_id=task_id, status='WAITING').update({'status': 'STARTED'})
    if changed:
        submission.publication_started_at = datetime.now()
        document.status = 'PROCESSANDO'
        db.session.commit()
    return jsonify(publish=bool(changed))


@relay_bp.post('/tasks/<int:task_id>/published')
def published(task_id):
    task, submission, document = task_rows(task_id)
    if task.status == 'WAITING':
        abort(409)
    if submission.published_at is None:
        submission.published_at = datetime.now()
    if document.status == 'PROCESSANDO':
        document.status = 'ENVIADO'
    db.session.commit()
    return jsonify(ok=True)


@relay_bp.post('/tasks/<int:task_id>/result')
def result(task_id):
    task, submission, document = task_rows(task_id)
    if task.status == 'WAITING':
        abort(409)
    if request.content_length is None or request.content_length > MAX_XML_BYTES:
        abort(413)
    xml = request.get_data()
    try:
        matched = apply_protocol(document, xml)
        if not matched:
            raise ValueError('Retorno não corresponde à nota.')
        root = ET.fromstring(xml)
    except Exception as exc:
        # Roll back any mutations made before XML validation failed.
        db.session.rollback()
        if isinstance(exc, (ValueError, ET.ParseError)) or type(exc).__module__.startswith('defusedxml'):
            return jsonify(error='Retorno fiscal inválido ou incompatível.'), 422
        raise
    # Keep polling after a bare authorization protocol until the processed XML
    # (invoice + protocol) is archived. Never trust a caller-supplied status.
    if document.status == 'DENEGADO' or (
        document.status == 'AUTORIZADO' and root.tag == '{%s}nfeProc' % NS['n']
    ):
        task.status = 'DONE'
    db.session.commit()
    return jsonify(ok=True, status=document.status)


@relay_bp.post('/tasks/<int:task_id>/problem')
def problem(task_id):
    task, submission, document = task_rows(task_id)
    if task.status == 'WAITING':
        abort(409)
    if request.content_length is None or request.content_length > 5000:
        abort(413)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get('error'), str):
        abort(400)
    if document.status not in {'AUTORIZADO', 'CANCELADO', 'DENEGADO'}:
        document.error_message = 'Conector Windows: ' + payload['error'][:1000]
    db.session.commit()
    return jsonify(ok=True)
