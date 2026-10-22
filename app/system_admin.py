from __future__ import annotations

from datetime import datetime, timedelta
from functools import wraps
import ipaddress
import secrets

import pyotp

import click
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for

from .company_focus import refresh_managed_companies
from .fiscal import save_fiscal_config_from_form
from .models import FiscalApiConfig, ManagedCompany, SystemAdmin, db
from .operations.models import AuditEvent
from .security import decrypt_secret, encrypt_secret
from .settings import get_system_settings
from .subscription import subscription_status


system_admin_bp = Blueprint('system_admin', __name__, url_prefix='/sistema')
SESSION_KEY = 'system_admin_id'


IDLE_MINUTES = 30
PENDING_KEY = 'system_admin_pending'


@system_admin_bp.before_request
def hide_from_unknown_networks():
    # Fora da lista de IPs permitidos o painel nem existe (404), para não revelar o endereço.
    allowed = [item.strip() for item in (current_app.config.get('SYSTEM_ADMIN_ALLOWED_IPS') or '').split(',') if item.strip()]
    if allowed and not _ip_allowed(request.remote_addr, allowed):
        abort(404)


@system_admin_bp.after_request
def no_index(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def _ip_allowed(address: str | None, allowed: list[str]) -> bool:
    try:
        ip = ipaddress.ip_address(address or '')
    except ValueError:
        return False
    return any(ip in ipaddress.ip_network(item, strict=False) for item in allowed)


def current_system_admin():
    admin_id = session.get(SESSION_KEY)
    admin = db.session.get(SystemAdmin, admin_id) if admin_id else None
    if not admin or not admin.active:
        return None
    last_seen = session.get('system_admin_seen', 0)
    if datetime.now().timestamp() - float(last_seen or 0) > IDLE_MINUTES * 60:
        session.clear()  # sessão parada por mais de 30 minutos expira
        return None
    session['system_admin_seen'] = datetime.now().timestamp()
    return admin


def system_admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_system_admin():
            return redirect(url_for('system_admin.login'))
        return view(*args, **kwargs)
    return wrapped


def _failures(ip_address: str) -> int:
    return AuditEvent.query.filter(
        AuditEvent.action == 'SYSTEM_ADMIN_LOGIN_FALHA',
        AuditEvent.ip_address == ip_address,
        AuditEvent.created_at >= datetime.now() - timedelta(minutes=15),
    ).count()


def _record_failure(ip_address: str, details: str) -> None:
    db.session.add(AuditEvent(action='SYSTEM_ADMIN_LOGIN_FALHA', entity_type='SystemAdmin', details=details, ip_address=ip_address))
    db.session.commit()


@system_admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_system_admin():
        return redirect(url_for('system_admin.dashboard'))
    if request.method == 'POST':
        ip_address = (request.remote_addr or '')[:64]
        if _failures(ip_address) >= 5:
            flash('Muitas tentativas. Aguarde 15 minutos para tentar novamente.', 'error')
            return render_template('sistema/login.html'), 429
        username = (request.form.get('username') or '').strip()
        admin = SystemAdmin.query.filter_by(username=username, active=True).first()
        if admin and admin.check_password(request.form.get('password') or ''):
            session.clear()
            session[PENDING_KEY] = {'id': admin.id, 'at': datetime.now().timestamp(),
                                    'secret': None if admin.mfa_secret_encrypted else pyotp.random_base32()}
            return redirect(url_for('system_admin.verify'))
        _record_failure(ip_address, 'Senha recusada no acesso administrativo.')
        flash('Usuário ou senha inválidos.', 'error')
    return render_template('sistema/login.html')


@system_admin_bp.route('/verificar', methods=['GET', 'POST'])
def verify():
    """Segunda etapa obrigatória: código do aplicativo autenticador (configurado no primeiro acesso)."""
    pending = session.get(PENDING_KEY) or {}
    admin = db.session.get(SystemAdmin, pending.get('id')) if pending.get('id') else None
    if not admin or not admin.active or datetime.now().timestamp() - float(pending.get('at') or 0) > 300:
        session.clear()
        flash('A verificação expirou. Entre novamente.', 'error')
        return redirect(url_for('system_admin.login'))
    setup_secret = pending.get('secret')
    if request.method == 'POST':
        ip_address = (request.remote_addr or '')[:64]
        if _failures(ip_address) >= 5:
            flash('Muitas tentativas. Aguarde 15 minutos para tentar novamente.', 'error')
            return render_template('sistema/login.html', step='codigo', setup_secret=setup_secret), 429
        secret = setup_secret or decrypt_secret(admin.mfa_secret_encrypted)
        if secret and pyotp.TOTP(secret).verify((request.form.get('otp') or '').strip(), valid_window=1):
            if setup_secret:
                admin.mfa_secret_encrypted = encrypt_secret(setup_secret)
            admin.last_login_at = datetime.now()
            db.session.commit()
            session.clear()
            session[SESSION_KEY] = admin.id
            session['system_admin_seen'] = datetime.now().timestamp()
            return redirect(url_for('system_admin.dashboard'))
        _record_failure(ip_address, 'Código de verificação recusado no acesso administrativo.')
        flash('Código inválido.', 'error')
    uri = pyotp.TOTP(setup_secret).provisioning_uri(name=admin.username, issuer_name='LS Hub Admin') if setup_secret else None
    return render_template('sistema/login.html', step='codigo', setup_secret=setup_secret, provisioning_uri=uri)


@system_admin_bp.post('/logout')
@system_admin_required
def logout():
    session.clear()
    return redirect(url_for('system_admin.login'))


@system_admin_bp.get('/admin')
@system_admin_required
def dashboard():
    query = ManagedCompany.query
    search = (request.args.get('q') or '').strip()
    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(ManagedCompany.legal_name.ilike(like), ManagedCompany.trade_name.ilike(like), ManagedCompany.document.ilike(like)))
    companies = query.order_by(ManagedCompany.remote_active.desc(), ManagedCompany.legal_name).all()
    config = FiscalApiConfig.query.order_by(FiscalApiConfig.id).first()
    return render_template(
        'sistema/dashboard.html', admin=current_system_admin(), companies=companies,
        search=search, local_company=get_system_settings(), fiscal_config=config,
        subscription_state=subscription_status(get_system_settings()),
        total_companies=ManagedCompany.query.filter_by(remote_active=True).count(),
        synced_companies=ManagedCompany.query.filter(ManagedCompany.remote_active.is_(True), ManagedCompany.remote_status.in_(['ATIVA', 'ATIVO', 'CADASTRADA'])).count(),
    )


@system_admin_bp.post('/admin/empresas/atualizar')
@system_admin_required
def refresh_companies():
    try:
        count = refresh_managed_companies()
        db.session.commit()
        flash(f'{count} empresa(s) atualizada(s) a partir da Focus NFe.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for('system_admin.dashboard'))


@system_admin_bp.route('/admin/integracao', methods=['GET', 'POST'])
@system_admin_required
def integration():
    if request.method == 'POST':
        try:
            save_fiscal_config_from_form(request.form)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
            return redirect(url_for('system_admin.integration'))
        db.session.commit()
        flash('Integração fiscal atualizada.', 'success')
        return redirect(url_for('system_admin.integration'))
    return render_template('sistema/integracao.html', admin=current_system_admin(), settings=get_system_settings(),
                           fiscal_config=FiscalApiConfig.query.order_by(FiscalApiConfig.id).first())


@system_admin_bp.post('/admin/assinatura')
@system_admin_required
def update_subscription():
    from .utils import parse_date
    settings = get_system_settings()
    if settings.id is None:
        db.session.add(settings)
    raw_date = (request.form.get('paid_until') or '').strip()
    paid_until = parse_date(raw_date) if raw_date else None
    if raw_date and not paid_until:
        flash('Data de pagamento inválida.', 'error')
        return redirect(url_for('system_admin.dashboard') + '#assinatura')
    settings.subscription_plan = (request.form.get('plan') or '').strip()[:40] or None
    settings.subscription_paid_until = paid_until
    settings.subscription_suspended = request.form.get('suspended') == '1'
    db.session.commit()
    flash('Assinatura atualizada.', 'success')
    return redirect(url_for('system_admin.dashboard') + '#assinatura')


@system_admin_bp.post('/admin/senha')
@system_admin_required
def change_password():
    admin = current_system_admin()
    current_password = request.form.get('current_password') or ''
    new_password = request.form.get('new_password') or ''
    if not admin.check_password(current_password):
        flash('A senha atual não confere.', 'error')
    elif len(new_password) < 12:
        flash('A nova senha deve ter pelo menos 12 caracteres.', 'error')
    else:
        admin.set_password(new_password)
        db.session.commit()
        flash('Senha administrativa atualizada.', 'success')
    return redirect(url_for('system_admin.dashboard') + '#seguranca')


def register_system_admin_cli(app):
    @app.cli.command('criar-admin-sistema')
    @click.option('--username', default='lucas.admin', show_default=True)
    @click.option('--name', default='Lucas - Proprietário', show_default=True)
    def create_system_admin(username, name):
        if SystemAdmin.query.first():
            raise click.ClickException('Já existe um administrador do sistema.')
        password = secrets.token_urlsafe(18)
        admin = SystemAdmin(username=username, display_name=name, active=True)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f'Usuário: {username}')
        click.echo(f'Senha temporária: {password}')

    @app.cli.command('redefinir-acesso-admin-sistema')
    @click.option('--username', required=True)
    def reset_system_admin(username):
        """Senha nova e autenticador zerado (refeito no próximo login). Só quem tem acesso ao servidor consegue."""
        admin = SystemAdmin.query.filter_by(username=username).first()
        if not admin:
            raise click.ClickException('Administrador não encontrado.')
        password = secrets.token_urlsafe(18)
        admin.set_password(password)
        admin.mfa_secret_encrypted = None
        admin.active = True
        db.session.commit()
        click.echo(f'Usuário: {username}')
        click.echo(f'Senha temporária: {password}')
        click.echo('No próximo login, configure o aplicativo autenticador.')

    @app.cli.command('atualizar-empresas-focus')
    def refresh_focus_companies_command():
        try:
            count = refresh_managed_companies()
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            raise click.ClickException(str(exc)) from exc
        click.echo(f'{count} empresa(s) sincronizada(s).')
