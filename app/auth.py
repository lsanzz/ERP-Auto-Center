from __future__ import annotations

from functools import wraps
from urllib.parse import urlsplit

from flask import abort, flash, redirect, request, session, url_for, g

from .models import User, db


SESSION_KEY = 'user_id'
USER_ROLES = ('ADMINISTRADOR', 'RECEPCIONISTA', 'MECANICO', 'ESTOQUISTA', 'FINANCEIRO')

ROLE_PERMISSIONS = {
    'ADMINISTRADOR': {'*'},
    'RECEPCIONISTA': {
        'dashboard.view', 'customers.manage', 'vehicles.view', 'vehicles.manage',
        'scheduling.view', 'scheduling.manage',
        'estimates.manage', 'work_orders.view', 'work_orders.manage', 'work_orders.progress',
        'approvals.manage',
    },
    'MECANICO': {
        'dashboard.view', 'vehicles.view', 'scheduling.view', 'work_orders.view',
        'work_orders.progress', 'inspections.manage', 'time_entries.manage',
    },
    'ESTOQUISTA': {'dashboard.view', 'inventory.view', 'inventory.move', 'purchases.manage'},
    'FINANCEIRO': {'dashboard.view', 'finance.view', 'finance.settle', 'finance.reconcile', 'reports.view'},
}


def current_user() -> User | None:
    user_id = session.get(SESSION_KEY)
    if not user_id:
        return None
    user = db.session.get(User, user_id)
    return user if user and user.ativo else None


def login_user(user: User) -> None:
    session.clear()
    g.pop('csrf_token', None)
    session[SESSION_KEY] = user.id


def logout_user() -> None:
    session.clear()
    g.pop('csrf_token', None)


def safe_next_url(value: str | None, fallback: str) -> str:
    """Return a same-origin absolute path suitable for a Location header."""
    if not value or '\\' in value or not value.startswith('/') or value.startswith('//'):
        return fallback
    try:
        parsed = urlsplit(value)
    except ValueError:
        return fallback
    if parsed.scheme or parsed.netloc:
        return fallback
    return value


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash('Faça login para continuar.', 'warning')
            return redirect(url_for('web.login', next=request.path))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return redirect(url_for('web.login'))
            if user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def has_permission(permission: str, user: User | None = None) -> bool:
    user = user or current_user()
    if not user:
        return False
    granted = ROLE_PERMISSIONS.get(user.role, set())
    return '*' in granted or permission in granted


def permission_required(permission: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user():
                return redirect(url_for('web.login', next=request.path))
            if not has_permission(permission):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


admin_required = role_required('ADMINISTRADOR')
