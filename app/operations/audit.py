import json

from flask import has_request_context, request, session as flask_session
from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session


_configured = False


def configure_automatic_audit():
    """Record model mutations without persisting field values or credentials."""
    global _configured
    if _configured:
        return
    _configured = True

    @event.listens_for(Session, 'before_flush')
    def audit_before_flush(session, _flush_context, _instances):
        from .models import AuditEvent
        if session.info.get('automatic_audit_running'):
            return
        session.info['automatic_audit_running'] = True
        try:
            user_id = flask_session.get('user_id') if has_request_context() else None
            ip = request.remote_addr if has_request_context() else None
            candidates = [(item, 'CRIAR') for item in session.new]
            candidates += [(item, 'EXCLUIR') for item in session.deleted]
            candidates += [(item, 'ALTERAR') for item in session.dirty if session.is_modified(item, include_collections=False)]
            for instance, action in candidates:
                if isinstance(instance, AuditEvent):
                    continue
                state = sa_inspect(instance)
                changed = [attr.key for attr in state.attrs if attr.history.has_changes() and attr.key not in {'password_hash', 'api_token', 'focus_management_token'}]
                audit = AuditEvent(
                    user_id=user_id, action=action, entity_type=instance.__class__.__name__.upper(),
                    entity_id=getattr(instance, 'id', None), details=json.dumps({'campos': changed}, ensure_ascii=False),
                    ip_address=(ip or '')[:64] or None,
                )
                session.add(audit)
                if action == 'CRIAR':
                    session.info.setdefault('audit_created_entities', []).append((instance, audit))
        finally:
            session.info.pop('automatic_audit_running', None)

    @event.listens_for(Session, 'after_flush_postexec')
    def assign_created_ids(session, _flush_context):
        for instance, audit in session.info.pop('audit_created_entities', []):
            audit.entity_id = getattr(instance, 'id', None)

    @event.listens_for(Session, 'after_soft_rollback')
    def discard_created_ids(session, _previous_transaction):
        session.info.pop('audit_created_entities', None)
