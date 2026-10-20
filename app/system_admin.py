from __future__ import annotations

from datetime import datetime, timedelta
from functools import wraps
import secrets

import click
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .company_focus import refresh_managed_companies
from .fiscal import save_fiscal_config_from_form
from .models import FiscalApiConfig, ManagedCompany, SystemAdmin, db
from .operations.models import AuditEvent
from .settings import get_system_settings


system_admin_bp = Blueprint('system_admin', __name__, url_prefix='/sistema')
SESSION_KEY = 'system_admin_id'


def current_system_admin():
    admin_id = session.get(SESSION_KEY)
    admin = db.session.get(SystemAdmin, admin_id) if admin_id else None
    return admin if admin and admin.active else None


def system_admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_system_admin():
            return redirect(url_for('system_admin.login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


@system_admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_system_admin():
        return redirect(url_for('system_admin.dashboard'))
    if request.method == 'POST':
        ip_address = (request.remote_addr or '')[:64]
        recent_failures = AuditEvent.query.filter(
            AuditEvent.action == 'SYSTEM_ADMIN_LOGIN_FALHA',
            AuditEvent.ip_address == ip_address,
            AuditEvent.created_at >= datetime.now() - timedelta(minutes=15),
        ).count()
        if recent_failures >= 5:
            flash('Muitas tentativas. Aguarde 15 minutos para tentar novamente.', 'error')
            return render_template('sistema/login.html'), 429
        username = (request.form.get('username') or '').strip()
        admin = SystemAdmin.query.filter_by(username=username, active=True).first()
        if admin and admin.check_password(request.form.get('password') or ''):
            session.clear()
            session[SESSION_KEY] = admin.id
            admin.last_login_at = datetime.now()
            db.session.commit()
            return redirect(url_for('system_admin.dashboard'))
        db.session.add(AuditEvent(action='SYSTEM_ADMIN_LOGIN_FALHA', entity_type='SystemAdmin',
                                  details='Tentativa de acesso administrativo recusada.', ip_address=ip_address))
        db.session.commit()
        flash('Usuário ou senha inválidos.', 'error')
    return render_template('sistema/login.html')


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

    @app.cli.command('atualizar-empresas-focus')
    def refresh_focus_companies_command():
        try:
            count = refresh_managed_companies()
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            raise click.ClickException(str(exc)) from exc
        click.echo(f'{count} empresa(s) sincronizada(s).')
