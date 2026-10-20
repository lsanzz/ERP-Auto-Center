"""Commit-before-publication orchestration for UniNFe.

A second invocation after an ambiguous attempt reads the monitor's return;
it never generates a second file just because the monitor consumed the first.
"""
from datetime import datetime
import hashlib
import json

from .models import FiscalDocument, UniNFeSubmission, db
from .uninfe_preparation import prepare
from .uninfe_transport import collect_return, publish_invoice, request_situation, _directory
from .uninfe_xml import build_invoice


def issue(document_id):
    document = db.session.get(FiscalDocument, document_id)
    if document is None or document.provider_name != 'UNINFE':
        raise ValueError('Documento UniNFe não encontrado.')
    if document.environment != 'HOMOLOGACAO':
        raise ValueError('O fluxo UniNFe está disponível apenas em homologação enquanto as regras fiscais de produção são completadas.')
    if document.status in {'AUTORIZADO', 'CANCELADO', 'DENEGADO'}:
        return document
    submission = prepare(document_id, build_invoice)
    config = json.loads(submission.snapshot_json)['config']
    if config.get('transport') == 'remote':
        from .uninfe_relay import enqueue_invoice
        enqueue_invoice(document, submission)
        db.session.commit()
        return document
    for field in ('send_directory', 'return_directory', 'authorized_directory'):
        _directory(config, field)
    # The exact XML/key/number and original folders must survive a process crash
    # before any irreversible interaction with the monitor.
    db.session.commit()
    submission = (UniNFeSubmission.query.filter_by(document_id=document_id)
                  .with_for_update().populate_existing().one())
    document = (FiscalDocument.query.filter_by(id=document_id)
                .with_for_update().populate_existing().one())
    if hashlib.sha256(submission.prepared_xml.encode('utf-8')).hexdigest() != submission.xml_sha256:
        raise ValueError('O XML preparado diverge do hash da reserva fiscal.')
    if document.access_key != submission.access_key:
        raise ValueError('A chave do documento diverge da reserva fiscal.')
    if submission.publication_started_at:
        # Release row locks before filesystem reads; no repeat publication.
        db.session.commit()
        collect_return(document, config)
        return document
    submission.publication_started_at = datetime.now()
    document.status = 'PROCESSANDO'
    document.error_message = None
    db.session.commit()
    try:
        publish_invoice(document, config, submission.prepared_xml)
    except Exception:
        # A failure after link/rename can be ambiguous. Keep the durable attempt
        # marker so job retries cannot enqueue the same invoice again.
        document.error_message = 'Envio inconclusivo. Consulte os retornos e o monitor UniNFe antes de tentar novamente.'
        db.session.commit()
        raise
    submission.published_at = datetime.now()
    db.session.query(FiscalDocument).filter_by(id=document_id, status='PROCESSANDO').update(
        {'status': 'ENVIADO'}, synchronize_session='fetch')
    db.session.commit()
    return document


def consult(document):
    submission = UniNFeSubmission.query.filter_by(document_id=document.id).first()
    if submission is None:
        raise ValueError('A nota ainda não foi preparada para o UniNFe.')
    config = json.loads(submission.snapshot_json)['config']
    if config.get('transport') == 'remote':
        # The Windows connector continuously returns local monitor results.
        # Never attempt to open Windows paths on the hosted server.
        return document
    from .uninfe_events import collect_cancellation
    collect_cancellation(document, submission)
    collect_return(document, config)
    if document.status not in {'CANCELADO', 'DENEGADO'}:
        request_situation(document, config)
    return document
