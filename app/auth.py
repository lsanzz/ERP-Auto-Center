from __future__ import annotations

from functools import wraps

from flask import abort, flash, redirect, request, session, url_for

from .models import User, db


SESSION_KEY = 'user_id'


def current_user() -> User | None:
    user_id = session.get(SESSION_KEY)
    if not user_id:
        return None
    return db.session.get(User, user_id)


def login_user(user: User) -> None:
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


admin_required = role_required('ADMINISTRADOR')
