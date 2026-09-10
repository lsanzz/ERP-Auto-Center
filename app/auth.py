from __future__ import annotations

from functools import wraps

from flask import abort, flash, redirect, request, session, url_for, g

from .models import User, db


SESSION_KEY = 'user_id'

ROLE_PERMISSIONS = {
    'ADMINISTRADOR': {'*'},
    'RECEPCIONISTA': {
        'dashboard.view', 'customers.manage', 'vehicles.manage', 'scheduling.manage',
        'estimates.manage', 'work_orders.view', 'approvals.manage',
    },
    'MECANICO': {'dashboard.view', 'work_orders.view', 'inspections.manage', 'time_entries.manage'},
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
    session.pop(SESSION_KEY, None)


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
