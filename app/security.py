from datetime import datetime, timedelta
import base64
import hashlib
import json
from urllib import parse as urlparse
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from flask import jsonify, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf
from werkzeug.exceptions import BadRequest


def login_is_rate_limited(ip_address: str | None, limit: int = 5, minutes: int = 15) -> bool:
    from .operations.models import AuditEvent
    from .models import db
    return db.session.query(AuditEvent.id).filter(
        AuditEvent.action == 'LOGIN_FALHA',
        AuditEvent.ip_address == (ip_address or '')[:64],
        AuditEvent.created_at >= datetime.now() - timedelta(minutes=minutes),
    ).count() >= limit


def _fernet() -> Fernet:
    digest = hashlib.sha256(current_app.config['SECRET_KEY'].encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode('utf-8')).decode('ascii')


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode('ascii')).decode('utf-8')
    except (InvalidToken, ValueError):
        return None


def verify_totp(user, code: str | None) -> bool:
    if not user.mfa_enabled:
        return True
    secret = decrypt_secret(user.mfa_secret_encrypted)
    return bool(secret and pyotp.TOTP(secret).verify((code or '').strip(), valid_window=1))


def verify_turnstile(token: str | None, ip_address: str | None, action: str = 'login') -> bool:
    """Validate a single-use Turnstile token with Cloudflare Siteverify."""
    if not current_app.config.get('TURNSTILE_ENABLED'):
        return True
    token = (token or '').strip()
    if not token or len(token) > 2048:
        return False
    payload = urlparse.urlencode({
        'secret': current_app.config['TURNSTILE_SECRET_KEY'],
        'response': token,
        'remoteip': ip_address or '',
    }).encode('utf-8')
    request_data = urlrequest.Request(
        'https://challenges.cloudflare.com/turnstile/v0/siteverify',
        data=payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'},
        method='POST',
    )
    try:
        with urlrequest.urlopen(request_data, timeout=6) as response:
            result = json.loads(response.read().decode('utf-8'))
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        current_app.logger.warning('turnstile_validation_unavailable')
        return False
    returned_action = result.get('action')
    return bool(result.get('success') and (not returned_action or returned_action == action))


def configure_security(app):
    if app.config.get('APP_ENV') == 'production':
        secret = app.config.get('SECRET_KEY') or ''
        if len(secret) < 32 or secret == 'erp-auto-center-secret':
            raise RuntimeError('Configure SECRET_KEY com pelo menos 32 caracteres em produção.')
        if not app.config.get('TURNSTILE_SITE_KEY') or not app.config.get('TURNSTILE_SECRET_KEY'):
            raise RuntimeError('Configure TURNSTILE_SITE_KEY e TURNSTILE_SECRET_KEY em produção.')
        app.config.update(SESSION_COOKIE_SECURE=True)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
    trusted_hosts = [host.strip() for host in app.config.get('TRUSTED_HOSTS', '').split(',') if host.strip()]
    if app.config.get('APP_ENV') == 'development':
        for local_host in ('localhost', '127.0.0.1'):
            if local_host not in trusted_hosts:
                trusted_hosts.append(local_host)
    if trusted_hosts and not app.config.get('TESTING'):
        app.config['TRUSTED_HOSTS'] = trusted_hosts
    elif app.config.get('TESTING'):
        app.config['TRUSTED_HOSTS'] = None
    CSRFProtect(app)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'camera=(self), microphone=(), geolocation=()')
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; connect-src 'self'; frame-src https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if app.config.get('APP_ENV') == 'production':
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        return response

    @app.get('/api/csrf')
    def csrf_token_endpoint():
        # Session-based clients fetch this token before login and after login.
        response = jsonify({'csrf_token': generate_csrf()})
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        message = 'Sua sessão expirou ou o formulário é inválido. Recarregue a página e tente novamente.'
        if request.path.startswith('/api/'):
            return jsonify({'error': message, 'code': 'CSRF_INVALID'}), 400
        return render_template('error.html', code=400, message=message), 400

    @app.errorhandler(BadRequest)
    def bad_request(error):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Requisição inválida.', 'code': 'BAD_REQUEST'}), 400
        return render_template('error.html', code=400, message='Não foi possível processar esta solicitação.'), 400
