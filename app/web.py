from __future__ import annotations

from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from collections import OrderedDict
import base64
import io
import json
import re
from datetime import date, datetime, time
from flask import abort, Blueprint, current_app, flash, redirect, render_template, request, send_file, session, url_for
from decimal import Decimal

from .auth import (
    USER_ROLES, admin_required, current_user, login_required, login_user, logout_user,
    has_permission, permission_required, safe_next_url,
)
from .cep import lookup_cep
from .cnpj import is_cnpj, is_cpf, lookup_cnpj, lookup_cpf
from .models import BankAccount, Budget, ChartOfAccount, Client, CompanyPartner, CostCenter, Employee, FinancialEntry, FiscalApiConfig, FiscalDocument, PaymentMethod, Product, Service, User, WorkOrder, WorkOrderItem, XmlInvoiceImport, db
from .services import (
    BUDGET_STATUSES,
    WORK_ORDER_STATUSES,
    add_budget_item,
    add_work_order_item,
    approve_budget,
    create_financial_entries,
    change_work_order_status,
    client_history,
    create_work_order_from_budget,
    dashboard_data,
    ensure_work_order_receivables,
    finalize_work_order,
    add_months,
    method_account_map,
    next_number,
    recalculate_budget_totals,
    recalculate_work_order_totals,
    remove_bank_account,
    replace_work_order_items,
    settle_financial_entry,
    split_installments,
    update_work_order_receivables,
    deduct_work_order_stock,
    record_work_order_status,
)
from .pdfs import generate_work_order_pdf
from .utils import parse_date, parse_decimal, format_currency
from .settings import budget_default_date, get_system_settings
from .xml_import import parse_nfe_xml
from .fiscal import (
    build_work_order_invoice_payload,
    apply_invoice_form,
    cancel_focus_nfe,
    cancel_focus_nfse,
    consult_focus_nfe,
    consult_focus_nfse,
    create_or_update_fiscal_document,
    create_parts_fiscal_document,
    decode_payload,
    get_fiscal_config,
    import_external_payload,
    import_nfe_xml_to_focus,
    issue_with_external_api,
    preview_external_import,
    sync_focus_company_certificate,
)


web_bp = Blueprint('web', __name__)
PAGE_SIZE = 20


def _page_number() -> int:
    try:
        return max(int(request.args.get('page', 1)), 1)
    except (TypeError, ValueError):
        return 1


def paginate_query(query, per_page: int = PAGE_SIZE) -> dict:
    page = _page_number()
    total = query.count()
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, pages)
    return {
        'items': query.offset((page - 1) * per_page).limit(per_page).all(),
        'page': page,
        'pages': pages,
        'total': total,
        'has_prev': page > 1,
        'has_next': page < pages,
    }


@web_bp.app_errorhandler(403)
def forbidden(_error):
    return render_template('error.html', code=403, message='Acesso negado.'), 403


@web_bp.app_errorhandler(404)
def not_found(_error):
    return render_template('error.html', code=404, message='Página não encontrada.'), 404


@web_bp.app_errorhandler(ValueError)
def invalid_value(_error):
    # IDs e números inválidos vindos de formulário/URL viram 400 em vez de 500; a API tem handler próprio.
    db.session.rollback()
    current_app.logger.warning('invalid_request_value', exc_info=True)
    return render_template('error.html', code=400, message='Algum dado enviado é inválido. Confira os campos e tente novamente.'), 400


@web_bp.get('/')
def root():
    return redirect(url_for('web.dashboard' if current_user() else 'web.login'))


@web_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user():
        return redirect(url_for('web.dashboard'))

    if request.method == 'POST':
        from .security import login_is_rate_limited, verify_turnstile
        from .operations.services import record_audit
        if login_is_rate_limited(request.remote_addr):
            return render_template('auth/login.html'), 429
        if not verify_turnstile(request.form.get('cf-turnstile-response'), request.remote_addr):
            record_audit('LOGIN_CAPTCHA_FALHA', 'SESSAO', None, None, ip=request.remote_addr)
            db.session.commit()
            flash('Não foi possível confirmar que você é uma pessoa. Tente novamente.', 'error')
            return render_template('auth/login.html'), 400
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, ativo=True).first()
        if user and user.check_password(password):
            if user.mfa_enabled:
                session['pending_login_user_id'] = user.id
                session['pending_login_at'] = datetime.now().timestamp()
                session['pending_login_next'] = safe_next_url(request.args.get('next'), '')
                return redirect(url_for('web.login_mfa'))
            record_audit('LOGIN_SUCESSO', 'SESSAO', None, user.id, ip=request.remote_addr)
            db.session.commit()
            login_user(user)
            flash('Login realizado com sucesso.', 'success')
            return redirect(safe_next_url(request.args.get('next'), url_for('web.dashboard')))
        record_audit('LOGIN_FALHA', 'SESSAO', None, user.id if user else None, {'usuario': username}, request.remote_addr)
        db.session.commit()
        flash('Usuário ou senha inválidos.', 'error')

    return render_template('auth/login.html')


@web_bp.route('/login/mfa', methods=['GET', 'POST'])
def login_mfa():
    user_id = session.get('pending_login_user_id')
    started_at = session.get('pending_login_at', 0)
    try:
        pending_expired = datetime.now().timestamp() - float(started_at or 0) > 300
    except (TypeError, ValueError):
        pending_expired = True
    if not user_id or pending_expired:
        session.pop('pending_login_user_id', None)
        session.pop('pending_login_at', None)
        session.pop('pending_login_next', None)
        flash('A verificação expirou. Entre novamente.', 'warning')
        return redirect(url_for('web.login'))
    user = db.session.get(User, user_id)
    if not user or not user.ativo or not user.mfa_enabled:
        return redirect(url_for('web.login'))
    if request.method == 'POST':
        from .security import login_is_rate_limited, verify_totp
        from .operations.services import record_audit
        if login_is_rate_limited(request.remote_addr):
            flash('Muitas tentativas. Aguarde alguns minutos antes de tentar novamente.', 'error')
            return render_template('auth/login_mfa.html'), 429
        if verify_totp(user, request.form.get('otp')):
            next_url = safe_next_url(session.get('pending_login_next'), url_for('web.dashboard'))
            record_audit('LOGIN_SUCESSO', 'SESSAO', None, user.id, ip=request.remote_addr)
            db.session.commit()
            login_user(user)
            flash('Login realizado com sucesso.', 'success')
            return redirect(next_url)
        record_audit('LOGIN_FALHA', 'SESSAO', None, user.id, {'etapa': 'mfa'}, request.remote_addr)
        db.session.commit()
        flash('Código temporário inválido.', 'error')
    return render_template('auth/login_mfa.html')


@web_bp.route('/configuracoes/mfa', methods=['GET', 'POST'])
@login_required
def mfa_setup():
    import pyotp
    from .security import encrypt_secret
    user = current_user()
    if request.method == 'POST' and request.form.get('disable') == '1':
        if not user.check_password(request.form.get('password', '')):
            flash('Senha atual inválida.', 'error')
        else:
            user.mfa_enabled = False
            user.mfa_secret_encrypted = None
            db.session.commit()
            flash('Verificação em duas etapas desativada.', 'success')
            return redirect(url_for('web.dashboard'))
    secret = session.get('pending_mfa_secret') or pyotp.random_base32()
    session['pending_mfa_secret'] = secret
    if request.method == 'POST' and request.form.get('enable') == '1':
        if not user.check_password(request.form.get('password', '')):
            flash('Senha atual inválida.', 'error')
        elif not pyotp.TOTP(secret).verify((request.form.get('otp') or '').strip(), valid_window=1):
            flash('Código temporário inválido.', 'error')
        else:
            user.mfa_secret_encrypted = encrypt_secret(secret)
            user.mfa_enabled = True
            session.pop('pending_mfa_secret', None)
            db.session.commit()
            flash('Verificação em duas etapas ativada.', 'success')
            return redirect(url_for('web.dashboard'))
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name='ERP Auto Center')
    return render_template('auth/mfa.html', secret=secret, provisioning_uri=uri)


@web_bp.post('/logout')
@login_required
def logout():
    logout_user()
    flash('Sessão encerrada.', 'success')
    return redirect(url_for('web.login'))


@web_bp.get('/dashboard')
@login_required
def dashboard():
    from .finance_overview import home_context
    return render_template('dashboard/overview.html', data=dashboard_data(current_user().role), **home_context(current_user().role))


@web_bp.get('/consultas/placa')
@login_required
@permission_required('vehicles.view')
def plate_lookup_page():
    return render_template('consultas/placa.html')


@web_bp.route('/configuracoes', methods=['GET'])
@login_required
@admin_required
def settings_index():
    from .uninfe_config import get_config
    fiscal_documents_page = paginate_query(FiscalDocument.query.order_by(FiscalDocument.id.desc()))
    users_page = paginate_query(User.query.order_by(User.nome))
    return render_template(
        'configuracoes/index.html',
        settings=get_system_settings(),
        uninfe=get_config(get_system_settings()),
        fiscal_documents=fiscal_documents_page['items'],
        fiscal_documents_pagination=fiscal_documents_page,
        users=users_page['items'],
        users_pagination=users_page,
    )


@web_bp.post('/configuracoes/empresa')
@login_required
@admin_required
def settings_save_company():
    settings = get_system_settings()
    previous_city = settings.city
    if settings.id is None:
        db.session.add(settings)
    settings.company_name = request.form.get('company_name', '').strip() or 'Japa Auto Center'
    text_fields = (
        'trade_name', 'company_document', 'phone', 'email', 'address', 'city', 'zip_code',
        'state_registration', 'municipal_registration', 'tax_regime', 'cnae', 'rntrc',
        'responsible_name', 'company_size', 'address_number', 'neighborhood',
        'address_complement', 'mobile', 'website', 'accountant_name', 'accountant_cpf',
        'accountant_cnpj', 'accountant_crc', 'accountant_email', 'accountant_phone',
        'accountant_zip_code', 'accountant_address', 'accountant_address_number',
        'accountant_neighborhood', 'accountant_complement', 'accountant_city',
    )
    for field in text_fields:
        setattr(settings, field, (request.form.get(field) or '').strip() or None)
    settings.person_type = request.form.get('person_type') if request.form.get('person_type') in {'JURIDICA', 'FISICA'} else 'JURIDICA'
    settings.state_registration_exempt = bool(request.form.get('state_registration_exempt'))
    settings.state = (request.form.get('state') or '').strip().upper()[:2] or None
    settings.accountant_state = (request.form.get('accountant_state') or '').strip().upper()[:2] or None
    from .uninfe_config import reconcile_company_config
    try:
        municipality_reset = reconcile_company_config(settings, previous_city=previous_city)
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return redirect(url_for('web.settings_index') + '#empresa')
    for day in ('weekdays', 'saturday', 'sunday'):
        setattr(settings, f'{day}_open', bool(request.form.get(f'{day}_open')))
        setattr(settings, f'{day}_from', (request.form.get(f'{day}_from') or '08:00')[:5])
        setattr(settings, f'{day}_to', (request.form.get(f'{day}_to') or ('18:00' if day == 'weekdays' else '12:00'))[:5])

    db.session.add(settings)
    db.session.flush()
    settings.partners.clear()
    partner_names = request.form.getlist('partner_name[]')
    partner_cpfs = request.form.getlist('partner_cpf[]')
    partner_emails = request.form.getlist('partner_email[]')
    partner_phones = request.form.getlist('partner_phone[]')
    partner_birth_dates = request.form.getlist('partner_birth_date[]')
    partner_rgs = request.form.getlist('partner_rg[]')
    partner_shares = request.form.getlist('partner_share[]')
    for index, raw_name in enumerate(partner_names):
        name = raw_name.strip()
        if not name:
            continue
        share_value = partner_shares[index].strip() if index < len(partner_shares) else ''
        settings.partners.append(CompanyPartner(
            full_name=name,
            cpf=(partner_cpfs[index].strip() if index < len(partner_cpfs) else '') or None,
            email=(partner_emails[index].strip() if index < len(partner_emails) else '') or None,
            phone=(partner_phones[index].strip() if index < len(partner_phones) else '') or None,
            birth_date=parse_date(partner_birth_dates[index]) if index < len(partner_birth_dates) else None,
            rg=(partner_rgs[index].strip() if index < len(partner_rgs) else '') or None,
            ownership_percentage=parse_decimal(share_value) if share_value else None,
        ))
    settings.focus_sync_status = 'PENDENTE'
    fiscal_config = FiscalApiConfig.query.order_by(FiscalApiConfig.id.asc()).first()
    if fiscal_config:
        fiscal_config.company_name = settings.trade_name or settings.company_name
        fiscal_config.company_document = settings.company_document
        fiscal_config.municipal_registration = settings.municipal_registration
        fiscal_config.state_registration = None if settings.state_registration_exempt else settings.state_registration
        fiscal_config.tax_regime = settings.tax_regime
        db.session.add(fiscal_config)
    db.session.commit()
    if not fiscal_config or fiscal_config.provider_name != 'FOCUSNFE' or not fiscal_config.active:
        flash('Dados da empresa salvos.', 'success')
        if municipality_reset:
            flash('A UF ou o município mudou. Informe o código IBGE do novo município nas configurações do UniNFe antes de emitir.', 'warning')
        return redirect(url_for('web.settings_index') + '#empresa')
    from .company_focus import sync_company
    try:
        sync_company(settings)
        db.session.commit()
        flash('Dados salvos e empresa sincronizada com a Focus NFe.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'warning')
    return redirect(url_for('web.settings_index') + '#empresa')


@web_bp.post('/configuracoes/empresa/uninfe')
@login_required
@admin_required
def settings_save_uninfe():
    from .uninfe_config import save_config
    try:
        save_config(get_system_settings(), request.form)
        db.session.commit()
        flash('Configurações do UniNFe salvas.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for('web.settings_index') + '#uninfe')


@web_bp.post('/configuracoes/empresa/certificado-focus')
@login_required
@admin_required
def settings_upload_focus_certificate():
    settings = get_system_settings()
    config = get_fiscal_config()
    upload = request.files.get('certificate_file')
    filename = (upload.filename if upload else '') or ''
    if not filename.lower().endswith(('.pfx', '.p12')):
        flash('Selecione um certificado A1 com extensão .pfx ou .p12.', 'error')
        return redirect(url_for('web.settings_index') + '#empresa')
    if not config:
        flash('Configure a integração com a Focus NFe antes de enviar o certificado.', 'error')
        return redirect(url_for('web.settings_index') + '#empresa')
    try:
        result = sync_focus_company_certificate(
            settings,
            config,
            upload.read(),
            request.form.get('certificate_password') or '',
        )
        settings.certificate_subject = result['subject']
        settings.certificate_serial_number = result['serial_number']
        settings.certificate_expires_at = result['expires_at']
        settings.certificate_synced_at = datetime.now()
        db.session.add(settings)
        db.session.add(config)
        db.session.commit()
        flash('Certificado A1 validado e enviado para a Focus NFe.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Não foi possível enviar o certificado: {exc}', 'error')
    return redirect(url_for('web.settings_index') + '#empresa')


@web_bp.post('/configuracoes/operacao')
@login_required
@admin_required
def settings_save_operation():
    settings = get_system_settings()
    if settings.id is None:
        db.session.add(settings)
    settings.budget_prefix = _settings_prefix(request.form.get('budget_prefix'), 'ORC')
    settings.work_order_prefix = _settings_prefix(request.form.get('work_order_prefix'), 'OS')
    settings.budget_validity_days = _settings_positive_int(request.form.get('budget_validity_days'), 7)
    settings.warranty_days = _settings_positive_int(request.form.get('warranty_days'), 90)
    db.session.commit()
    flash('Parâmetros operacionais atualizados.', 'success')
    return redirect(url_for('web.settings_index'))


@web_bp.post('/configuracoes/perfil')
@login_required
def settings_save_profile():
    user = current_user()
    user.nome = request.form.get('nome', '').strip() or user.nome
    new_password = request.form.get('new_password') or ''
    if new_password:
        if not user.check_password(request.form.get('current_password') or ''):
            flash('A senha atual não confere.', 'error')
            return redirect(url_for('web.settings_index'))
        if len(new_password) < 12:
            flash('A nova senha deve ter pelo menos 12 caracteres.', 'error')
            return redirect(url_for('web.settings_index'))
        user.set_password(new_password)
    db.session.commit()
    flash('Seu perfil foi atualizado.', 'success')
    return redirect(url_for('web.settings_index'))


@web_bp.route('/configuracoes/usuarios/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def settings_users_new():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password') or ''
        role = request.form.get('role')
        if not username or len(password) < 12:
            flash('Informe usuário e uma senha com pelo menos 12 caracteres.', 'error')
        elif role not in USER_ROLES:
            flash('Selecione um perfil de acesso válido.', 'error')
        elif User.query.filter_by(username=username).first():
            flash('Este usuário já existe.', 'error')
        else:
            user = User(username=username, nome=request.form.get('nome', '').strip() or username, role=role, ativo=bool(request.form.get('ativo')))
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Usuário criado.', 'success')
            return redirect(url_for('web.settings_index'))
    return render_template('configuracoes/usuario_form.html', user=None)


@web_bp.route('/configuracoes/usuarios/<int:user_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def settings_users_edit(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        return redirect(url_for('web.settings_index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        duplicate = User.query.filter(User.username == username, User.id != user.id).first()
        password = request.form.get('password') or ''
        role = request.form.get('role')
        if duplicate:
            flash('Este usuário já existe.', 'error')
        elif not username or (password and len(password) < 12):
            flash('Usuário inválido ou senha menor que 12 caracteres.', 'error')
        elif role not in USER_ROLES:
            flash('Selecione um perfil de acesso válido.', 'error')
        elif user.role == 'ADMINISTRADOR' and user.ativo and (role != 'ADMINISTRADOR' or not request.form.get('ativo')) and User.query.filter_by(role='ADMINISTRADOR', ativo=True).count() <= 1:
            flash('Mantenha pelo menos um administrador ativo no sistema.', 'error')
        elif user.id == current_user().id and (not request.form.get('ativo') or role != 'ADMINISTRADOR'):
            flash('Você não pode remover o próprio acesso de administrador.', 'error')
        else:
            user.username = username
            user.nome = request.form.get('nome', '').strip() or user.nome
            user.role = role
            user.ativo = bool(request.form.get('ativo'))
            if password:
                user.set_password(password)
            db.session.commit()
            flash('Usuário atualizado.', 'success')
            return redirect(url_for('web.settings_index'))
    return render_template('configuracoes/usuario_form.html', user=user)




@web_bp.post('/contas-bancarias/nova')
@login_required
@admin_required
def bank_accounts_new():
    account = BankAccount(
        nome=request.form.get('nome', '').strip(),
        banco=request.form.get('banco') or None,
        agencia=request.form.get('agencia') or None,
        conta=request.form.get('conta') or None,
        saldo_inicial=parse_decimal(request.form.get('saldo_inicial')),
        saldo_atual=parse_decimal(request.form.get('saldo_atual') or request.form.get('saldo_inicial')),
        ativo=bool(request.form.get('ativo', '1')),
    )
    db.session.add(account)
    db.session.commit()
    flash('Conta bancária cadastrada.', 'success')
    return redirect(url_for('web.dashboard'))


@web_bp.post('/contas-bancarias/<int:account_id>/editar')
@login_required
@admin_required
def bank_accounts_edit(account_id: int):
    account = db.session.get(BankAccount, account_id)
    if not account:
        return redirect(url_for('web.dashboard'))
    account.nome = request.form.get('nome', '').strip()
    account.banco = request.form.get('banco') or None
    account.agencia = request.form.get('agencia') or None
    account.conta = request.form.get('conta') or None
    account.saldo_inicial = parse_decimal(request.form.get('saldo_inicial'))
    account.saldo_atual = parse_decimal(request.form.get('saldo_atual'))
    db.session.commit()
    flash('Conta bancária atualizada.', 'success')
    return redirect(url_for('web.dashboard'))


@web_bp.post('/contas-bancarias/<int:account_id>/remover')
@login_required
@admin_required
def bank_accounts_delete(account_id: int):
    account = db.session.get(BankAccount, account_id)
    if not account:
        return redirect(url_for('web.dashboard'))
    history_preserved = remove_bank_account(account)
    db.session.commit()
    if history_preserved:
        flash('Conta bancária removida da lista. O histórico financeiro foi preservado.', 'success')
    else:
        flash('Conta bancária removida.', 'success')
    return redirect(url_for('web.dashboard'))

@web_bp.route('/clientes')
@login_required
@permission_required('customers.manage')
def clients_index():
    termo_pesquisa = request.args.get('q', '').strip()
    query = Client.query
    
    if termo_pesquisa:
        filtro = f"%{termo_pesquisa}%"
        query = query.filter(
            db.or_(
                Client.nome.ilike(filtro),
                Client.cpf_cnpj.ilike(filtro)
            )
        )
    
    clientes = query.order_by(Client.nome).limit(100).all()
    return render_template('clientes/index.html', clientes=clientes)


@web_bp.get('/clientes/buscar')
@login_required
@permission_required('customers.manage')
def clients_lookup():
    """JSON used by client pickers so forms do not embed every client."""
    query = Client.query
    term = request.args.get('q', '').strip()
    if term:
        like = f'%{term}%'
        query = query.filter(db.or_(Client.nome.ilike(like), Client.cpf_cnpj.ilike(like), Client.telefone.ilike(like)))
    return {'items': [{'id': client.id, 'nome': client.nome,
                       'detalhe': ' · '.join(filter(None, [client.telefone, client.cpf_cnpj]))}
                      for client in query.order_by(Client.nome).limit(20)]}


@web_bp.get('/api/cep/<cep>')
@login_required
@permission_required('customers.manage')
def cep_lookup(cep: str):
    try:
        return lookup_cep(cep)
    except ValueError as exc:
        return {'error': str(exc)}, 400
    except LookupError as exc:
        return {'error': str(exc)}, 404
    except RuntimeError as exc:
        return {'error': str(exc)}, 502


@web_bp.route('/clientes/novo', methods=['GET', 'POST'])
@login_required
@permission_required('customers.manage')
def clients_new():
    if request.method == 'POST':
        client = Client()
        _fill_client_from_form(client)
        db.session.add(client)
        db.session.commit()
        flash('Cliente cadastrado.', 'success')
        return redirect(url_for('web.clients_index'))
    return render_template('clientes/form.html', client=None)


@web_bp.route('/clientes/<int:client_id>/editar', methods=['GET', 'POST'])
@login_required
@permission_required('customers.manage')
def clients_edit(client_id: int):
    client = db.session.get(Client, client_id)
    if not client:
        return redirect(url_for('web.clients_index'))
    if request.method == 'POST':
        _fill_client_from_form(client)
        db.session.commit()
        flash('Cliente atualizado.', 'success')
        return redirect(url_for('web.clients_show', client_id=client.id))
    return render_template('clientes/form.html', client=client)


@web_bp.get('/clientes/<int:client_id>')
@login_required
@permission_required('customers.manage')
def clients_show(client_id: int):
    client = db.session.get(Client, client_id)
    if not client:
        return redirect(url_for('web.clients_index'))
    return render_template('clientes/show.html', client=client, history=client_history(client.id))

@web_bp.route('/produtos')
@login_required
def products_index():
    termo_pesquisa = request.args.get('q', '').strip()
    query = Product.query
    
    if termo_pesquisa:
        filtro = f"%{termo_pesquisa}%"
        query = query.filter(
            db.or_(
                Product.nome.ilike(filtro),
                Product.codigo.ilike(filtro)
            )
        )
        
    page = paginate_query(query.order_by(Product.nome))
    low_stock_count = Product.query.filter(Product.estoque_minimo > 0, Product.estoque_atual <= Product.estoque_minimo).count()
    
    return render_template('produtos/index.html', products=page['items'], low_stock_count=low_stock_count, pagination=page)

@web_bp.route('/produtos/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def products_new():
    if request.method == 'POST':
        product = Product()
        _fill_product_from_form(product)
        db.session.add(product)
        db.session.flush()
        from .operations.services import register_inventory_change
        register_inventory_change(product, 0, 'SALDO_INICIAL', 'CADASTRO', current_user().id)
        db.session.commit()
        flash('Peça cadastrada.', 'success')
        return redirect(url_for('web.products_index'))
    return render_template('produtos/form.html', product=None)


@web_bp.route('/produtos/<int:product_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def products_edit(product_id: int):
    product = db.session.get(Product, product_id)
    if not product:
        return redirect(url_for('web.products_index'))
    if request.method == 'POST':
        previous_stock = product.estoque_atual
        _fill_product_from_form(product)
        from .operations.services import register_inventory_change
        register_inventory_change(product, previous_stock, 'AJUSTE', 'EDICAO_PRODUTO', current_user().id)
        db.session.commit()
        flash('Peça atualizada.', 'success')
        return redirect(url_for('web.products_index'))
    return render_template('produtos/form.html', product=product)

@web_bp.route('/produtos/importar-xml/preview', methods=['GET', 'POST'])
@web_bp.route('/entrada-mercadoria/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def products_import_xml_preview():
    upload = request.files.get('xml_file') if request.method == 'POST' else None
    filename = upload.filename if upload and upload.filename else None
    if not filename:
        flash('Selecione o arquivo XML da nota.', 'error')
        return redirect(url_for('operations.inventory'))
    raw_xml = upload.read()

    try:
        parsed = parse_nfe_xml(raw_xml)
        
        # Verificar se o fornecedor já existe
        fornecedor = Client.query.filter_by(cpf_cnpj=parsed.get('emitente_cnpj')).first()
        parsed['fornecedor_cadastrado'] = bool(fornecedor)

        for item in parsed.get('itens', []):
            existing = Product.query.filter_by(codigo=item['codigo']).first()
            item['exists'] = bool(existing)
            if existing:
                item['nome_sugerido'] = existing.nome
                item['margem_sugerida'] = 0.0 
                item['preco_venda_sugerido'] = float(existing.preco_venda)
                item['cadastrado'] = True
            else:
                item['nome_sugerido'] = item['descricao']
                item['margem_sugerida'] = 0.0
                item['preco_venda_sugerido'] = float(item['valor_unitario'])
                item['cadastrado'] = False

        # Envia o XML cru encodado para podermos ler depois na confirmação
        raw_xml_b64 = base64.b64encode(raw_xml).decode('ascii')
        all_products = Product.query.filter_by(ativo=True).order_by(Product.nome.asc()).all()

        return render_template(
            'produtos/xml_preview.html',
            parsed=parsed,
            raw_xml_b64=raw_xml_b64,
            filename=filename or (parsed.get('chave_acesso', 'nota') + '.xml'),
            all_products=all_products
        )
    except Exception as exc:
        flash(f'Falha ao ler XML: {exc}', 'error')
        return redirect(url_for('operations.inventory'))


@web_bp.post('/produtos/importar-xml/confirmar')
@login_required
@admin_required
def products_import_xml_confirm():
    codigos = request.form.getlist('codigo[]')
    nomes = request.form.getlist('nome[]')
    unidades = request.form.getlist('unidade[]')
    custos = request.form.getlist('custo[]')
    precos_venda = request.form.getlist('preco_venda[]')
    acoes_cadastro = request.form.getlist('acao_cadastro[]') # 'sim', 'nao', 'substituir'
    substituir_ids = request.form.getlist('substituir_produto_id[]')
    
    lancar_estoque = request.form.get('lancar_estoque') == '1'
    lancar_contas = request.form.get('lancar_contas') == '1'
    forma_pagamento = request.form.get('forma_pagamento') or 'Boleto'
    
    raw_xml_b64 = request.form.get('raw_xml_b64')

    novos = 0
    atualizados = 0

    try:
        raw_xml = base64.b64decode(raw_xml_b64.encode('ascii')) if raw_xml_b64 else b''
        parsed = parse_nfe_xml(raw_xml) if raw_xml else {'itens': []}
        
        # 1. Salva/atualiza os produtos no catálogo
        for idx, codigo in enumerate(codigos):
            acao = acoes_cadastro[idx] if idx < len(acoes_cadastro) else 'sim'
            if acao == 'nao':
                continue

            custo_val = parse_decimal(custos[idx]) if idx < len(custos) else Decimal('0')
            venda_val = parse_decimal(precos_venda[idx]) if idx < len(precos_venda) else Decimal('0')
            xml_item = parsed['itens'][idx] if idx < len(parsed.get('itens', [])) else {}
            item_qty = parse_decimal(xml_item.get('quantidade', '1')) if lancar_estoque else Decimal('0')
            product = None
            old_stock = Decimal('0')

            if acao == 'substituir':
                sub_id = substituir_ids[idx] if idx < len(substituir_ids) else None
                product = db.session.get(Product, sub_id) if sub_id else None
                if product:
                    old_stock = product.estoque_atual
                    product.custo = custo_val
                    product.preco_venda = venda_val
                    if lancar_estoque:
                        product.estoque_atual = parse_decimal(product.estoque_atual) + item_qty
                    atualizados += 1
            else: # acao == 'sim'
                product = Product.query.filter_by(codigo=codigo).first()
                if product:
                    old_stock = product.estoque_atual
                    product.nome = nomes[idx]
                    product.unidade = unidades[idx] if idx < len(unidades) else product.unidade
                    product.custo = custo_val
                    product.preco_venda = venda_val
                    product.ncm = xml_item.get('ncm') or product.ncm
                    product.cfop = xml_item.get('cfop') or product.cfop
                    if lancar_estoque:
                        product.estoque_atual = parse_decimal(product.estoque_atual) + item_qty
                    atualizados += 1
                else:
                    product = Product(
                        codigo=codigo,
                        nome=nomes[idx] if idx < len(nomes) else (xml_item.get('descricao') or codigo),
                        unidade=unidades[idx] if idx < len(unidades) else 'UN',
                        custo=custo_val,
                        preco_venda=venda_val,
                        estoque_atual=item_qty,
                        ncm=xml_item.get('ncm'),
                        cfop=xml_item.get('cfop'),
                        ativo=True
                    )
                    db.session.add(product)
                    novos += 1
            
            db.session.flush()
            if product and lancar_estoque:
                from .operations.services import register_inventory_change
                register_inventory_change(product, old_stock, 'ENTRADA_XML', parsed.get('numero') or 'XML', current_user().id)

        # 2. Registra o XML e lança no Financeiro (Contas a Pagar), se solicitado
        if lancar_contas and raw_xml_b64:
            existing_xml = XmlInvoiceImport.query.filter_by(chave_acesso=parsed['chave_acesso']).first()
            if not existing_xml:
                supplier = Client.query.filter_by(cpf_cnpj=parsed.get('emitente_cnpj')).first()
                if not supplier:
                    supplier = Client(
                        nome=parsed.get('emitente_nome') or 'Fornecedor XML',
                        cpf_cnpj=parsed.get('emitente_cnpj'),
                        inscricao_estadual=parsed.get('emitente_ie') if parsed.get('emitente_ie') != '-' else None,
                        endereco=parsed.get('emitente_endereco'),
                        telefone=parsed.get('emitente_telefone')
                    )
                    db.session.add(supplier)
                    db.session.flush()

                xml_import = XmlInvoiceImport(
                    chave_acesso=parsed['chave_acesso'],
                    numero=parsed.get('numero'),
                    serie=parsed.get('serie'),
                    natureza_operacao=parsed.get('natureza_operacao'),
                    emitente_nome=parsed.get('emitente_nome'),
                    emitente_cnpj=parsed.get('emitente_cnpj'),
                    destinatario_nome=parsed.get('destinatario_nome'),
                    destinatario_cnpj=parsed.get('destinatario_cnpj'),
                    total_nota=parse_decimal(parsed.get('total_nota')),
                    emissao_em=parse_date(parsed.get('issued_at')),
                    informacoes_complementares=parsed.get('informacoes_complementares'),
                    raw_xml=raw_xml.decode('utf-8', errors='ignore')
                )
                xml_import.set_items(parsed.get('itens') or [])
                db.session.add(xml_import)
                db.session.flush()
                
                faturas = parsed.get('faturas')
                if faturas:
                    for fatura in faturas:
                        data_venc = fatura.get('vencimento') or parsed.get('issued_at')
                        create_financial_entries(
                            entry_type='PAGAR',
                            descricao=f"NF-e {parsed.get('numero')} - {parsed.get('emitente_nome')} (Dup. {fatura['numero']}) - {forma_pagamento}",
                            categoria='NF-e XML',
                            valor_total=parse_decimal(fatura['valor']),
                            vencimento=data_venc,
                            status='PENDENTE',
                            reference_type='XML_NFE',
                            reference_id=xml_import.id,
                            installment_count=1
                        )
                else:
                    data_venc = parsed.get('issued_at')
                    create_financial_entries(
                        entry_type='PAGAR',
                        descricao=f"NF-e {parsed.get('numero')} - {parsed.get('emitente_nome')} - {forma_pagamento}",
                        categoria='NF-e XML',
                        valor_total=parse_decimal(parsed.get('total_nota')),
                        vencimento=data_venc,
                        status='PENDENTE',
                        reference_type='XML_NFE',
                        reference_id=xml_import.id,
                        installment_count=1
                    )

        db.session.commit()
        msg = f'Importação concluída com sucesso! {novos} peça(s) nova(s) e {atualizados} atualizada(s).'
        if lancar_contas:
            msg += ' Contas a pagar registradas no financeiro.'
        flash(msg, 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Falha ao importar mercadorias: {exc}', 'error')

    return redirect(url_for('operations.inventory'))


@web_bp.get('/servicos')
@login_required
def services_index():
    page = paginate_query(Service.query.order_by(Service.nome))
    return render_template('servicos/index.html', services=page['items'], pagination=page)


@web_bp.route('/servicos/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def services_new():
    if request.method == 'POST':
        service = Service()
        _fill_service_from_form(service)
        db.session.add(service)
        db.session.commit()
        flash('Serviço cadastrado.', 'success')
        return redirect(url_for('web.services_index'))
    return render_template('servicos/form.html', service=None)


@web_bp.route('/servicos/<int:service_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def services_edit(service_id: int):
    service = db.session.get(Service, service_id)
    if not service:
        return redirect(url_for('web.services_index'))
    if request.method == 'POST':
        _fill_service_from_form(service)
        db.session.commit()
        flash('Serviço atualizado.', 'success')
        return redirect(url_for('web.services_index'))
    return render_template('servicos/form.html', service=service)


@web_bp.get('/orcamentos')
@login_required
@permission_required('estimates.manage')
def budgets_index():
    page = paginate_query(Budget.query.order_by(Budget.id.desc()))
    return render_template('orcamentos/index.html', budgets=page['items'], pagination=page)


@web_bp.route('/orcamentos/novo', methods=['GET', 'POST'])
@login_required
@permission_required('estimates.manage')
def budgets_new():
    if request.method == 'POST':
        budget = Budget(numero=next_number(Budget, get_system_settings().budget_prefix or 'ORC'))
        try:
            _fill_budget_from_form(budget)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
            return render_template('orcamentos/form.html', budget=budget, statuses=BUDGET_STATUSES), 400
        db.session.add(budget)
        db.session.commit()
        flash('Orçamento criado.', 'success')
        return redirect(url_for('web.budgets_show', budget_id=budget.id))
    return render_template('orcamentos/form.html', budget=None, statuses=BUDGET_STATUSES, budget_default_date=budget_default_date())

@web_bp.post('/orcamentos/<int:budget_id>/excluir')
@login_required
@admin_required
def budgets_delete(budget_id: int):
    budget = db.session.get(Budget, budget_id)
    if not budget:
        return redirect(url_for('web.budgets_index'))
    db.session.delete(budget)
    db.session.commit()
    flash('Orçamento excluído com sucesso.', 'success')
    return redirect(url_for('web.budgets_index'))


@web_bp.route('/orcamentos/<int:budget_id>/editar', methods=['GET', 'POST'])
@login_required
@permission_required('estimates.manage')
def budgets_edit(budget_id: int):
    budget = db.session.get(Budget, budget_id)
    if not budget:
        return redirect(url_for('web.budgets_index'))
    if request.method == 'POST':
        try:
            _fill_budget_from_form(budget)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
            return render_template('orcamentos/form.html', budget=budget, statuses=BUDGET_STATUSES), 400
        if 'status' in request.form:
            budget.status = request.form.get('status') or budget.status
        recalculate_budget_totals(budget)
        db.session.commit()
        flash('Orçamento atualizado.', 'success')
        return redirect(url_for('web.budgets_show', budget_id=budget.id))
    return render_template('orcamentos/form.html', budget=budget, statuses=BUDGET_STATUSES)


@web_bp.get('/orcamentos/<int:budget_id>')
@login_required
@permission_required('estimates.manage')
def budgets_show(budget_id: int):
    budget = db.session.get(Budget, budget_id)
    if not budget:
        return redirect(url_for('web.budgets_index'))
    services = Service.query.filter_by(ativo=True).order_by(Service.nome).all()
    products = Product.query.filter_by(ativo=True).order_by(Product.nome).all()
    return render_template('orcamentos/show.html', budget=budget, services=services, products=products)


@web_bp.post('/orcamentos/<int:budget_id>/itens')
@login_required
@permission_required('estimates.manage')
def budgets_add_item(budget_id: int):
    budget = db.session.get(Budget, budget_id)
    if not budget:
        return redirect(url_for('web.budgets_index'))
    try:
        item_type, reference_id = _resolve_item_payload(request.form)
        add_budget_item(budget, item_type=item_type, reference_id=reference_id, quantidade=request.form.get('quantidade'), desconto=request.form.get('desconto'))
        db.session.commit()
        flash('Item adicionado ao orçamento.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for('web.budgets_show', budget_id=budget.id))


@web_bp.post('/orcamentos/<int:budget_id>/aprovar')
@login_required
@permission_required('estimates.manage')
def budgets_approve(budget_id: int):
    budget = db.session.get(Budget, budget_id)
    if not budget:
        return redirect(url_for('web.budgets_index'))
    approve_budget(budget)
    db.session.commit()
    flash('Orçamento aprovado.', 'success')
    return redirect(url_for('web.budgets_show', budget_id=budget.id))


@web_bp.post('/orcamentos/<int:budget_id>/converter-os')
@login_required
@permission_required('estimates.manage')
def budgets_convert(budget_id: int):
    budget = db.session.get(Budget, budget_id)
    if not budget:
        return redirect(url_for('web.budgets_index'))
    try:
        order = create_work_order_from_budget(budget)
        db.session.commit()
        flash('O.S. criada a partir do orçamento.', 'success')
        return redirect(url_for('web.work_orders_show', work_order_id=order.id))
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return redirect(url_for('web.budgets_show', budget_id=budget.id))


@web_bp.route('/os')
@login_required
@permission_required('work_orders.view')
def work_orders_index():
    termo_pesquisa = request.args.get('q', '').strip()
    
    # ⚡ OTIMIZAÇÃO: Traz OS, Cliente, Funcionário e Pagamento em 1 única viagem ao banco
    query = WorkOrder.query.options(
        joinedload(WorkOrder.client),
        joinedload(WorkOrder.employee),
        joinedload(WorkOrder.payment_method)
    )
    
    if termo_pesquisa:
        filtro = f"%{termo_pesquisa}%"
        query = query.filter(
            db.or_(
                WorkOrder.numero.ilike(filtro),
                WorkOrder.client_nome.ilike(filtro),
                WorkOrder.placa.ilike(filtro)
            )
        )
        
    # Busca avançada: todos opcionais; datas e valores inválidos são ignorados.
    args = request.args
    if args.get('status') in WORK_ORDER_STATUSES:
        query = query.filter(WorkOrder.status == args['status'])
    if args.get('tipo') in ('INTERNO', 'EXTERNO', 'GARANTIA'):
        query = query.filter(WorkOrder.tipo_atendimento == args['tipo'])
    for key, compare in (('de', WorkOrder.data_entrada.__ge__), ('ate', WorkOrder.data_entrada.__le__)):
        try:
            day = parse_date(args.get(key))
        except ValueError:
            day = None
        if day:
            query = query.filter(compare(day))
    for key, compare in (('valor_min', WorkOrder.total_geral.__ge__), ('valor_max', WorkOrder.total_geral.__le__)):
        if args.get(key):
            try:
                query = query.filter(compare(parse_decimal(args.get(key))))
            except (ArithmeticError, ValueError):
                pass
    sort_columns = {'numero': WorkOrder.id, 'data': WorkOrder.data_entrada, 'cliente': WorkOrder.client_nome, 'total': WorkOrder.total_geral}
    sort = args.get('ordem') if args.get('ordem') in sort_columns else 'numero'
    column = sort_columns[sort]
    direction = 'asc' if args.get('dir') == 'asc' else 'desc'
    orders_page = paginate_query(query.order_by(column.asc() if direction == 'asc' else column.desc(), WorkOrder.id.desc()))
    orders = orders_page['items']
    
    receivables_by_order: dict[int, list[FinancialEntry]] = {}
    if current_user().role == 'ADMINISTRADOR' and orders:
        order_ids = [order.id for order in orders]
        receivables = (
            FinancialEntry.query.filter(
                FinancialEntry.reference_type == 'OS',
                FinancialEntry.reference_id.in_(order_ids),
                FinancialEntry.entry_type == 'RECEBER',
            )
            .order_by(FinancialEntry.reference_id.asc(), FinancialEntry.installment_number.asc(), FinancialEntry.id.asc())
            .all()
        )
        for entry in receivables:
            receivables_by_order.setdefault(entry.reference_id, []).append(entry)
            
    payment_methods = PaymentMethod.query.filter_by(ativo=True).order_by(PaymentMethod.nome).all() if current_user().role == 'ADMINISTRADOR' else []
    bank_accounts = BankAccount.query.filter_by(ativo=True).order_by(BankAccount.nome).all() if current_user().role == 'ADMINISTRADOR' else []
    
    employees = Employee.query.filter_by(ativo=True).order_by(Employee.nome).all() if has_permission('work_orders.manage') else []
    return render_template('os/index.html', orders=orders, pagination=orders_page, sort=sort, direction=direction, employees=employees, statuses=WORK_ORDER_STATUSES, receivables_by_order=receivables_by_order, payment_methods=payment_methods, bank_accounts=bank_accounts, method_accounts=method_account_map() if bank_accounts else {}, today=date.today())

@web_bp.post('/os/<int:work_order_id>/copiar')
@login_required
@permission_required('work_orders.manage')
def work_orders_copy(work_order_id: int):
    source = db.session.get(WorkOrder, work_order_id)
    if not source:
        return redirect(url_for('web.work_orders_index'))
    copy = WorkOrder(
        client_id=source.client_id,
        employee_id=source.employee_id,
        payment_method_id=source.payment_method_id,
        numero=next_number(WorkOrder, get_system_settings().work_order_prefix or 'OS'),
        status='ABERTA',
        vehicle_id=source.vehicle_id if source.vehicle and source.vehicle.client_id == source.client_id and source.vehicle.ativo else None,
        placa=source.placa,
        veiculo_descricao=source.veiculo_descricao,
        observacoes=f'Copiada da O.S. {source.numero}. {source.observacoes or ""}'.strip(),
        installment_count=source.installment_count or 1,
        client_nome=source.client_nome,
    )
    db.session.add(copy)
    db.session.flush()
    for item in source.items:
        db.session.add(WorkOrderItem(
            work_order=copy,
            item_type=item.item_type,
            reference_id=item.reference_id,
            descricao=item.descricao,
            quantidade=item.quantidade,
            valor_unitario=item.valor_unitario,
            desconto=item.desconto,
            total=item.total,
        ))
    recalculate_work_order_totals(copy)
    record_work_order_status(copy, 'ABERTA', current_user().id, 'O.S. copiada')
    db.session.commit()
    flash(f'O.S. {copy.numero} criada a partir de {source.numero}.', 'success')
    return redirect(url_for('web.work_orders_show', work_order_id=copy.id))


@web_bp.route('/os/nova', methods=['GET', 'POST'])
@login_required
@permission_required('work_orders.manage')
def work_orders_new():
    order = None
    if request.method == 'POST':
        order = WorkOrder(numero=next_number(WorkOrder, get_system_settings().work_order_prefix or 'OS'), status=request.form.get('status') or 'ABERTA')
        try:
            _fill_work_order_from_form(order)
            db.session.add(order)
            db.session.flush()
            record_work_order_status(order, order.status, current_user().id, 'O.S. cadastrada')
            _sync_work_order_items_from_form(order)
            _sync_work_order_payments_from_form(order)
            recalculate_work_order_totals(order)
            db.session.commit()
            flash('O.S. cadastrada.', 'success')
            return redirect(url_for('web.work_orders_show', work_order_id=order.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
    return _render_work_order_form(order)


@web_bp.route('/os/<int:work_order_id>/editar', methods=['GET', 'POST'])
@login_required
@permission_required('work_orders.manage')
def work_orders_edit(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    if request.method == 'POST':
        try:
            previous_status = order.status
            _fill_work_order_from_form(order)
            _sync_work_order_items_from_form(order)
            _sync_work_order_payments_from_form(order)
            if 'status' in request.form and request.form.get('status') in WORK_ORDER_STATUSES:
                order.status = request.form.get('status')
                if order.status != previous_status:
                    record_work_order_status(order, order.status, current_user().id, request.form.get('observation'))
            recalculate_work_order_totals(order)
            db.session.commit()
            flash('O.S. atualizada.', 'success')
            return redirect(url_for('web.work_orders_show', work_order_id=order.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
    return _render_work_order_form(order)


@web_bp.get('/os/<int:work_order_id>')
@login_required
@permission_required('work_orders.view')
def work_orders_show(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    installment_values = split_installments(order.total_geral, order.installment_count or 1) if order.payment_method and order.payment_method.permite_parcelamento else []
    receivables = FinancialEntry.query.filter_by(reference_type='OS', reference_id=order.id, entry_type='RECEBER').order_by(FinancialEntry.installment_number.asc(), FinancialEntry.id.asc()).all()
    return render_template(
        'os/show.html',
        order=order,
        statuses=WORK_ORDER_STATUSES,
        service_items=[item for item in order.items if item.item_type == 'SERVICO'],
        part_items=[item for item in order.items if item.item_type == 'PECA'],
        installment_values=installment_values,
        receivables=receivables,
        payment_methods=PaymentMethod.query.filter_by(ativo=True).order_by(PaymentMethod.nome).all() if current_user().role == 'ADMINISTRADOR' else [],
        bank_accounts=BankAccount.query.filter_by(ativo=True).order_by(BankAccount.nome).all() if current_user().role == 'ADMINISTRADOR' else [],
        method_accounts=method_account_map() if current_user().role == 'ADMINISTRADOR' else {},
        today=date.today(),
        status_history=order.status_history,
        whatsapp_url=whatsapp_url(order),
    )



def whatsapp_url(order: WorkOrder) -> str | None:
    """Link wa.me com mensagem pronta; o envio é feito pelo próprio WhatsApp do usuário."""
    from urllib.parse import quote
    from .cnpj import only_digits
    phone = only_digits(order.client.telefone if order.client else '')
    if len(phone) in (10, 11):
        phone = '55' + phone  # número brasileiro sem DDI
    if len(phone) not in (12, 13):
        return None
    company = get_system_settings().company_name or 'a oficina'
    name = (order.client_nome or (order.client.nome if order.client else '')).split(' ')[0].title()
    vehicle = ' '.join(filter(None, [order.veiculo_descricao, order.placa]))
    if order.status in ('FINALIZADA', 'ENTREGUE'):
        body = f'seu veículo {vehicle} está pronto para retirada.'
    else:
        body = f'segue a ordem de serviço do veículo {vehicle}.'
    text = (f'Olá{" " + name if name else ""}, aqui é da {company}: {body}\n'
            f'O.S. {order.numero} · Total {format_currency(order.total_geral)}')
    return f'https://wa.me/{phone}?text={quote(text)}'


@web_bp.get('/os/<int:work_order_id>/pdf')
@login_required
@permission_required('work_orders.view')
def work_orders_pdf(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    is_receipt = request.args.get('recibo') == '1'
    production = request.args.get('producao') == '1'
    pdf_bytes = generate_work_order_pdf(
        order,
        [item for item in order.items if item.item_type == 'SERVICO'],
        [item for item in order.items if item.item_type == 'PECA'],
        company_name=get_system_settings().company_name or 'ERP Auto Center',
        document_title='ORDEM DE PRODUÇÃO' if production else 'RECIBO COMPLETO DA O.S.' if is_receipt else 'ORDEM DE SERVIÇO',
        production=production,
    )
    return send_file(
        __import__('io').BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=request.args.get('download') != '0',
        download_name=f'{"producao" if production else "recibo" if is_receipt else "os"}-{order.numero}.pdf',
    )


@web_bp.post('/os/<int:work_order_id>/itens')
@login_required
@permission_required('work_orders.manage')
def work_orders_add_item(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    try:
        try:
            item_type, reference_id = _resolve_item_payload(request.form)
        except ValueError:
            item_type = (request.form.get('item_type') or '').upper()
            item_type = 'PECA' if item_type in {'PRODUTO', 'PECA'} else 'SERVICO'
            reference_id = None
        add_work_order_item(
            order,
            item_type=item_type,
            reference_id=reference_id,
            quantidade=request.form.get('quantidade'),
            desconto=request.form.get('desconto'),
            descricao=request.form.get('descricao'),
            valor_unitario=request.form.get('valor_unitario'),
            total=request.form.get('total'),
        )
        db.session.commit()
        flash('Item adicionado à O.S..', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for('web.work_orders_show', work_order_id=order.id))




@web_bp.post('/os/<int:work_order_id>/status')
@login_required
@permission_required('work_orders.progress')
def work_orders_change_status(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    try:
        status = request.form.get('status', '')
        change_work_order_status(order, status)
        if status in {'FINALIZADA', 'ENTREGUE'} and request.form.get('data_saida'):
            order.data_saida = parse_date(request.form.get('data_saida'))
        record_work_order_status(order, status, current_user().id, request.form.get('observation'))
        db.session.commit()
        flash(f'O.S. {order.numero}: situação alterada para {status.replace("_", " ").lower()}.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _back_to_list_or(order)


def _back_to_list_or(order: WorkOrder):
    """Volta para a lista de onde veio (com filtros e na linha da O.S.) ou para a própria O.S."""
    target = safe_next_url(request.form.get('next'), '')
    if target:
        return redirect(f'{target}#os-{order.id}')
    return redirect(url_for('web.work_orders_show', work_order_id=order.id))


@web_bp.post('/os/<int:work_order_id>/responsavel')
@login_required
@permission_required('work_orders.manage')
def work_orders_change_employee(work_order_id: int):
    order = db.get_or_404(WorkOrder, work_order_id)
    employee_id = request.form.get('employee_id', type=int)
    employee = db.session.get(Employee, employee_id) if employee_id else None
    if employee_id and (not employee or not employee.ativo):
        flash('Funcionário não encontrado ou inativo.', 'error')
        return _back_to_list_or(order)
    order.employee_id = employee.id if employee else None
    db.session.commit()
    flash(f'O.S. {order.numero}: responsável {"alterado para " + employee.nome if employee else "removido"}.', 'success')
    return _back_to_list_or(order)


@web_bp.post('/os/<int:work_order_id>/lancar-estoque')
@login_required
@admin_required
def work_orders_launch_stock(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    if order.status not in {'FINALIZADA', 'ENTREGUE'}:
        flash('Finalize ou entregue a O.S. antes de lançar o estoque.', 'error')
    elif order.estoque_baixado:
        flash('O estoque desta O.S. já foi lançado.', 'warning')
    else:
        warnings = deduct_work_order_stock(order)
        db.session.commit()
        flash('Estoque lançado com sucesso.', 'success')
        for warning in warnings:
            flash(warning, 'warning')
    return redirect(url_for('web.work_orders_index'))


@web_bp.post('/os/<int:work_order_id>/finalizar')
@login_required
@permission_required('work_orders.manage')
def work_orders_finish(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    was_finalized = order.status == 'FINALIZADA'
    order.status = 'FINALIZADA'
    if not order.data_saida:
        order.data_saida = parse_date(request.form.get('data_saida')) or __import__('datetime').date.today()
    recalculate_work_order_totals(order)
    if not was_finalized:
        record_work_order_status(order, 'FINALIZADA', current_user().id, 'O.S. finalizada')
    from .operations.services import ensure_warranty
    ensure_warranty(order)
    db.session.commit()
    flash('O.S. finalizada. Use as ações da ordem para imprimir ou lançar o contas a receber.', 'success')
    return redirect(url_for('web.work_orders_index'))


@web_bp.post('/os/<int:work_order_id>/lancar-contas')
@login_required
@admin_required
def work_orders_launch_receivables(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    if order.status not in {'FINALIZADA', 'ENTREGUE'}:
        flash('Finalize ou entregue a O.S. antes de lançar o contas a receber.', 'error')
        return redirect(url_for('web.work_orders_index'))
    try:
        method_id = request.form.get('payment_method_id', type=int)
        if method_id and not order.payments:
            order.payment_method_id = method_id
            order.installment_count = max(request.form.get('installment_count', 1, type=int) or 1, 1)
        entries = ensure_work_order_receivables(order)
        first_due = parse_date(request.form.get('vencimento'))
        if first_due:
            for entry in entries:
                if entry.status == 'PENDENTE':
                    entry.vencimento = add_months(first_due, entry.installment_number - 1)
        received = request.form.get('receivable_status') == 'RECEBIDO'
        if received:
            for entry in entries:
                # Conta em branco: cada parcela vai para a conta padrão da sua forma de pagamento.
                settle_financial_entry(entry, payment_receipt_at=request.form.get('payment_receipt_at'),
                                       bank_account_id=request.form.get('bank_account_id', type=int))
        db.session.commit()
        total = len(entries)
        flash(f'{total} parcela(s) lançada(s) e recebida(s).' if received else f'{total} parcela(s) lançada(s) em contas a receber.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    target = request.form.get('next', '')
    if target.startswith('/') and not target.startswith('//'):  # only same-site paths
        return redirect(target)
    return redirect(url_for('web.work_orders_show', work_order_id=order.id))


@web_bp.post('/os/<int:work_order_id>/atualizar-recebimento')
@login_required
@admin_required
def work_orders_update_receivables(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    try:
        status = request.form.get('receivable_status', 'PENDENTE')
        method_id = int(request.form.get('payment_method_id')) if request.form.get('payment_method_id') else None
        bank_account_id = int(request.form.get('bank_account_id')) if request.form.get('bank_account_id') else None
        entries = update_work_order_receivables(
            order,
            status=status,
            payment_method_id=method_id,
            payment_receipt_at=request.form.get('payment_receipt_at'),
            bank_account_id=bank_account_id,
        )
        db.session.commit()
        if status == 'RECEBIDO':
            flash(f'Recebimento da O.S. {order.numero} atualizado para recebido.', 'success')
        else:
            flash(f'Recebimento da O.S. {order.numero} atualizado para pendente.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for('web.work_orders_index'))


def _financial_status_slug(status: str | None) -> str:
    return (status or 'pendente').strip().lower().replace(' ', '-').replace('_', '-')


def _financial_group_key(entry: FinancialEntry) -> str:
    base_desc = re.sub(r'\s*\(\d+/\d+\)$', '', (entry.descricao or '').strip())
    created = entry.created_at.isoformat() if entry.created_at else f'id-{entry.id}'
    ref_type = entry.reference_type or ''
    ref_id = entry.reference_id or ''
    return f"{entry.entry_type}|{base_desc}|{entry.categoria or ''}|{ref_type}|{ref_id}|{created}"


def _group_financial_entries(entries: list[FinancialEntry]) -> list[dict]:
    groups = OrderedDict()
    for entry in entries:
        key = _financial_group_key(entry) if (entry.installment_total or 1) > 1 else f'single-{entry.id}'
        base_desc = re.sub(r'\s*\(\d+/\d+\)$', '', (entry.descricao or '').strip())
        if key not in groups:
            groups[key] = {
                'key': key,
                'entry_type': entry.entry_type,
                'descricao': base_desc or entry.descricao,
                'categoria': entry.categoria,
                'installment_total': entry.installment_total or 1,
                'entries': [],
                'valor_total': 0,
                'first_due_date': entry.vencimento,
                'reference_type': entry.reference_type,
                'reference_id': entry.reference_id,
                'payment_method': entry.payment_method.nome if entry.payment_method else '-',
                'bank_account': entry.bank_account.nome if entry.bank_account else '-',
                'status_slug': _financial_status_slug(entry.status),
                'status_label': entry.status or 'PENDENTE',
                'status_counts': {},
            }
        group = groups[key]
        group['entries'].append(entry)
        group['valor_total'] += parse_decimal(entry.valor)
        if entry.vencimento and (not group['first_due_date'] or entry.vencimento < group['first_due_date']):
            group['first_due_date'] = entry.vencimento
        status = entry.status or 'PENDENTE'
        group['status_counts'][status] = group['status_counts'].get(status, 0) + 1

    results = []
    for group in groups.values():
        status_counts = group['status_counts']
        if len(status_counts) == 1:
            group['status_label'] = next(iter(status_counts.keys()))
        else:
            group['status_label'] = 'PARCIAL'
            group['status_slug'] = 'parcial'
        pending_count = status_counts.get('PENDENTE', 0)
        if pending_count == 0 and status_counts:
            first = next(iter(status_counts.keys()))
            group['status_slug'] = _financial_status_slug(first)
        group['entry_count'] = len(group['entries'])
        group['is_grouped'] = group['entry_count'] > 1
        group['summary_value'] = format_currency(group['valor_total'])
        results.append(group)
    return results


@web_bp.route('/financeiro')
@login_required
@permission_required('finance.view')
def finance_index():
    from .finance_overview import render_finance
    return render_finance()

def finance_form_context() -> dict:
    return dict(
        payment_methods=PaymentMethod.query.filter_by(ativo=True).order_by(PaymentMethod.nome).all(),
        bank_accounts=BankAccount.query.filter_by(ativo=True).order_by(BankAccount.nome).all(),
        chart_accounts=ChartOfAccount.query.filter_by(active=True).order_by(ChartOfAccount.code).all(),
        cost_centers=CostCenter.query.filter_by(active=True).order_by(CostCenter.name).all(),
        method_accounts=method_account_map(),
        categories=[row[0] for row in db.session.query(FinancialEntry.categoria).filter(FinancialEntry.categoria.isnot(None))
                    .distinct().order_by(FinancialEntry.categoria).limit(300)],
    )


@web_bp.route('/financeiro/novo', methods=['GET', 'POST'])
@login_required
@permission_required('finance.view')
def finance_new():
    if request.method == 'GET':
        return render_template('financeiro/form.html', **finance_form_context())

    entry_type = request.form.get('entry_type') or 'RECEBER'
    if entry_type not in {'RECEBER', 'PAGAR'}:
        flash('Selecione se o lançamento é uma receita ou uma despesa.', 'error')
        return redirect(url_for('web.finance_new'))

    description = request.form.get('descricao', '').strip()
    total_value = parse_decimal(request.form.get('valor'))
    try:
        installment_count = max(int(request.form.get('installment_count') or 1), 1)
    except (TypeError, ValueError):
        installment_count = 0

    if not description:
        flash('Informe uma descrição para o lançamento.', 'error')
        return redirect(url_for('web.finance_new', entry_type=entry_type))
    if total_value <= 0:
        flash('Informe um valor total maior que zero.', 'error')
        return redirect(url_for('web.finance_new', entry_type=entry_type))
    if installment_count < 1 or installment_count > 120:
        flash('Informe uma quantidade de parcelas entre 1 e 120.', 'error')
        return redirect(url_for('web.finance_new', entry_type=entry_type))

    requested_status = request.form.get('status') or 'PENDENTE'
    status = ('RECEBIDO' if entry_type == 'RECEBER' else 'PAGO') if requested_status == 'LIQUIDADO' else 'PENDENTE'
    from .services import default_bank_account_id
    method_id = int(request.form.get('payment_method_id')) if request.form.get('payment_method_id') else None
    bank_account_id = (int(request.form.get('bank_account_id')) if request.form.get('bank_account_id')
                       else default_bank_account_id(method_id))
    if status != 'PENDENTE' and not bank_account_id:
        flash('Selecione a conta bancária para criar um lançamento já liquidado.', 'error')
        return redirect(url_for('web.finance_new', entry_type=entry_type))
        
    entries = create_financial_entries(
        entry_type=entry_type,
        descricao=description,
        categoria=request.form.get('categoria') or None,
        valor_total=total_value,
        vencimento=request.form.get('vencimento'),
        status=status,
        payment_method_id=int(request.form.get('payment_method_id')) if request.form.get('payment_method_id') else None,
        bank_account_id=bank_account_id,
        reference_type=request.form.get('reference_type') or None,
        reference_id=int(request.form.get('reference_id')) if request.form.get('reference_id') else None,
        installment_count=installment_count,
        payment_receipt_at=request.form.get('payment_receipt_at'),
    )
    issued_on = parse_date(request.form.get('issued_on')) or parse_date(request.form.get('vencimento'))
    competence_on = parse_date(request.form.get('competence_on')) or issued_on
    for entry in entries:
        entry.issued_on = issued_on
        entry.competence_on = competence_on
        entry.chart_account_id = request.form.get('chart_account_id', type=int)
        entry.cost_center_id = request.form.get('cost_center_id', type=int)
    db.session.commit()
    flash(f'{len(entries)} lançamento(s) financeiro(s) criado(s).', 'success')
    return redirect(url_for('web.finance_index'))


@web_bp.get('/financeiro/importacoes')
@login_required
@admin_required
def finance_imports():
    xml_imports_page = paginate_query(XmlInvoiceImport.query.order_by(XmlInvoiceImport.id.desc()))
    return render_template('financeiro/importacoes.html', xml_imports=xml_imports_page['items'], xml_imports_pagination=xml_imports_page)


@web_bp.post('/financeiro/<int:entry_id>/liquidar')
@login_required
@admin_required
def finance_settle(entry_id: int):
    entry = db.session.get(FinancialEntry, entry_id)
    if not entry:
        return redirect(url_for('web.finance_index'))
    try:
        settle_financial_entry(
            entry,
            payment_method_id=int(request.form.get('payment_method_id')) if request.form.get('payment_method_id') else None,
            payment_receipt_at=request.form.get('payment_receipt_at'),
            bank_account_id=int(request.form.get('bank_account_id')) if request.form.get('bank_account_id') else None,
            valor_baixa=request.form.get('valor_baixa'),
            juros=request.form.get('juros'),
            desconto=request.form.get('desconto'),
            taxa=request.form.get('taxa'),
            acrescimo=request.form.get('acrescimo'),
            observacoes_pagamento=request.form.get('observacoes_pagamento'),
        )
        db.session.commit()
        flash('Lançamento liquidado.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    target = request.form.get('next', '')
    if target.startswith('/') and not target.startswith('//'):  # only same-site paths
        return redirect(target)
    return redirect(url_for('web.finance_index'))




@web_bp.get('/financeiro/xml/<int:xml_id>/preview')
@login_required
@admin_required
def finance_xml_preview(xml_id: int):
    xml_import = db.session.get(XmlInvoiceImport, xml_id)
    if not xml_import:
        return redirect(url_for('web.finance_index'))
    parsed = parse_nfe_xml(xml_import.raw_xml.encode('utf-8')) if xml_import.raw_xml else xml_import.to_dict()
    parsed['itens'] = parsed.get('itens') or xml_import.get_items()
    document_error = None
    linked_documents = FiscalDocument.query.filter(FiscalDocument.work_order_id.is_(None), FiscalDocument.document_type.in_(['NFE', 'NFCE'])).order_by(FiscalDocument.id.desc()).limit(PAGE_SIZE).all()
    for linked_document in linked_documents:
        try:
            linked_payload = json.loads(linked_document.request_payload or '{}')
        except json.JSONDecodeError:
            linked_payload = {}
        if str(linked_payload.get('source_xml_id') or '') == str(xml_import.id):
            document_error = linked_document.error_message
            break
    return render_template('financeiro/xml_preview_saved.html', xml_import=xml_import, parsed=parsed, document_error=document_error)


@web_bp.get('/financeiro/xml/<int:xml_id>/exportar')
@login_required
@admin_required
def finance_xml_export(xml_id: int):
    xml_import = db.session.get(XmlInvoiceImport, xml_id)
    if not xml_import or not xml_import.raw_xml:
        flash('XML não encontrado para exportação.', 'error')
        return redirect(url_for('web.finance_index'))
    return send_file(
        io.BytesIO(xml_import.raw_xml.encode('utf-8')),
        mimetype='application/xml',
        as_attachment=True,
        download_name=f'nfe_{xml_import.numero or xml_import.id}.xml',
    )


@web_bp.post('/financeiro/importar-sistema/preview')
@login_required
@admin_required
def finance_import_other_system_preview():
    upload = request.files.get('system_file')
    if not upload or not upload.filename:
        flash('Selecione um arquivo JSON de outro sistema.', 'error')
        return redirect(url_for('web.finance_index'))
    try:
        payload = json.loads(upload.read().decode('utf-8'))
        preview = preview_external_import(payload)
        return render_template('financeiro/import_other_preview.html', preview=preview, payload_b64=base64.b64encode(json.dumps(payload, ensure_ascii=False).encode('utf-8')).decode('ascii'))
    except Exception as exc:
        flash(f'Falha ao preparar importação: {exc}', 'error')
        return redirect(url_for('web.finance_index'))


@web_bp.post('/financeiro/importar-sistema/confirmar')
@login_required
@admin_required
def finance_import_other_system_confirm():
    payload_b64 = request.form.get('payload_b64') or ''
    if not payload_b64:
        flash('Prévia de importação expirada. Envie o arquivo novamente.', 'error')
        return redirect(url_for('web.finance_index'))
    try:
        payload = json.loads(base64.b64decode(payload_b64.encode('ascii')).decode('utf-8'))
        created = import_external_payload(payload)
        db.session.commit()
        flash(f"Importação concluída: {created['work_orders']} O.S., {created['financial_entries']} lançamentos financeiros e {created['bank_accounts']} contas bancárias.", 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Falha ao importar dados de outro sistema: {exc}', 'error')
    return redirect(url_for('web.finance_index'))


@web_bp.get('/fiscal')
@login_required
@admin_required
def fiscal_index():
    from .business_reports import render_fiscal_center
    return render_fiscal_center()


@web_bp.post('/fiscal/focus/importar-nfe')
@login_required
@admin_required
def fiscal_focus_import_nfe():
    config = get_fiscal_config()
    upload = request.files.get('xml_file')
    if not config or config.provider_name != 'FOCUSNFE':
        flash('Configure o provedor Focus NFe antes de importar XML pela API.', 'error')
        return redirect(url_for('web.fiscal_index'))
    if not upload or not upload.filename:
        flash('Selecione um arquivo XML de NF-e.', 'error')
        return redirect(url_for('web.fiscal_index'))
    try:
        result = import_nfe_xml_to_focus(upload.read(), config, request.form.get('ref') or None)
        flash(f"XML enviado para a Focus NFe. Status: {result.get('status') or 'recebido'}.", 'success')
    except Exception as exc:
        flash(f'Falha ao importar XML na Focus NFe: {exc}', 'error')
    return redirect(url_for('web.fiscal_index'))


@web_bp.route('/fiscal/nfe-pecas/nova', methods=['GET', 'POST'])
@login_required
@admin_required
def fiscal_parts_invoice_new():
    config = get_fiscal_config()
    xml_imports = XmlInvoiceImport.query.order_by(XmlInvoiceImport.emissao_em.desc(), XmlInvoiceImport.id.desc()).limit(PAGE_SIZE).all()
    products = Product.query.filter_by(ativo=True).order_by(Product.nome).all()
    selected_product = db.session.get(Product, int(request.args.get('product_id'))) if request.args.get('product_id') else None
    source_import = db.session.get(XmlInvoiceImport, int(request.args.get('xml_import_id'))) if request.args.get('xml_import_id') else None
    source_details = parse_nfe_xml(source_import.raw_xml.encode('utf-8')) if source_import and source_import.raw_xml else None
    
    # Busca se o fornecedor do XML já está cadastrado no sistema
    supplier_client = None
    missing_fields = []
    if source_import and source_import.emitente_cnpj:
        supplier_client = Client.query.filter_by(cpf_cnpj=source_import.emitente_cnpj).first()
        if supplier_client:
            if not getattr(supplier_client, 'inscricao_estadual', None):
                missing_fields.append('Inscrição Estadual')
            if not supplier_client.endereco:
                missing_fields.append('Endereço completo')
        else:
            missing_fields.append('Fornecedor não cadastrado no sistema')

    if request.method == 'POST':
        form = request.form.copy()
        document = None
        document_id = None
        xml_import = db.session.get(XmlInvoiceImport, int(form.get('xml_import_id'))) if form.get('xml_import_id') else None
        source_import = xml_import or source_import
        source_details = parse_nfe_xml(source_import.raw_xml.encode('utf-8')) if source_import and source_import.raw_xml else source_details
        
        if xml_import and form.get('finalidade_emissao') == '4':
            db_client = Client.query.filter_by(cpf_cnpj=xml_import.emitente_cnpj).first()
            form['chave_referenciada'] = xml_import.chave_acesso
            form['cliente_nome'] = form.get('cliente_nome') or (db_client.nome if db_client else xml_import.emitente_nome) or ''
            form['cliente_documento'] = form.get('cliente_documento') or xml_import.emitente_cnpj or ''
            form['cliente_ie'] = form.get('cliente_ie') or (getattr(db_client, 'inscricao_estadual', None) if db_client else '') or ''
            form['cliente_telefone'] = form.get('cliente_telefone') or (db_client.telefone if db_client else (source_details or {}).get('emitente_telefone')) or ''
            form['cliente_endereco'] = form.get('cliente_endereco') or (db_client.endereco if db_client else (source_details or {}).get('emitente_endereco')) or ''
            
        if not (form.get('cliente_nome') or '').strip():
            flash('Informe o cliente/fornecedor da NF-e.', 'error')
            return render_template('fiscal/parts_invoice.html', config=config, form=form, xml_imports=xml_imports, products=products, selected_product=selected_product, source_import=source_import, source_details=source_details, supplier_client=supplier_client, missing_fields=missing_fields, invoice_items=_parts_invoice_form_items(form, source_import, selected_product), clients=Client.query.order_by(Client.nome.asc()).all(), employees=Employee.query.filter_by(ativo=True).order_by(Employee.nome.asc()).all())
            
        if not any((value or '').strip() for value in form.getlist('item_descricao')):
            flash('Informe pelo menos um produto.', 'error')
            return render_template('fiscal/parts_invoice.html', config=config, form=form, xml_imports=xml_imports, products=products, selected_product=selected_product, source_import=source_import, source_details=source_details, supplier_client=supplier_client, missing_fields=missing_fields, invoice_items=_parts_invoice_form_items(form, source_import, selected_product), clients=Client.query.order_by(Client.nome.asc()).all(), employees=Employee.query.filter_by(ativo=True).order_by(Employee.nome.asc()).all())
            
        try:
            document = create_parts_fiscal_document(form, config)
            apply_invoice_form(document, form)
            document_id = document.id
            db.session.commit()
            if form.get('emitir'):
                if not config:
                    raise ValueError('Configure a integração fiscal antes de emitir.')
                issue_with_external_api(document, config)
                db.session.commit()
            if form.get('emitir') and document.status == 'ERRO':
                flash(f'Emissão recusada: {document.error_message or "verifique o documento fiscal"}', 'error')
            else:
                flash(f'NF-e encaminhada. Status: {document.status}.' if form.get('emitir') else 'NF-e de peças salva como preparada.', 'success')
            return redirect(url_for('web.settings_index') + '#fiscal-documentos')
        except Exception as exc:
            db.session.rollback()
            if document_id:
                failed_document = db.session.get(FiscalDocument, document_id)
                if failed_document:
                    failed_document.status = 'ERRO'
                    failed_document.error_message = str(exc)
                    db.session.commit()
            flash(f'Falha ao preparar NF-e de peças: {exc}', 'error')
            
    return render_template('fiscal/parts_invoice.html', config=config, form=request.form, xml_imports=xml_imports, products=products, selected_product=selected_product, source_import=source_import, source_details=source_details, supplier_client=supplier_client, missing_fields=missing_fields, invoice_items=_parts_invoice_form_items(request.form, source_import, selected_product), clients=Client.query.order_by(Client.nome.asc()).all(), employees=Employee.query.filter_by(ativo=True).order_by(Employee.nome.asc()).all())

def _parts_invoice_form_items(form, source_import=None, selected_product=None) -> list[dict]:
    descriptions = form.getlist('item_descricao')
    if descriptions:
        quantities = form.getlist('item_quantidade')
        prices = form.getlist('item_valor_unitario')
        cfops = form.getlist('item_cfop')
        ncms = form.getlist('item_ncm')
        units = form.getlist('item_unidade')
        return [
            {
                'descricao': descriptions[index],
                'quantidade': quantities[index] if index < len(quantities) else '1',
                'valor_unitario': prices[index] if index < len(prices) else '',
                'cfop': cfops[index] if index < len(cfops) else '5102',
                'ncm': ncms[index] if index < len(ncms) else '',
                'unidade': units[index] if index < len(units) else 'UN',
            }
            for index in range(len(descriptions))
        ]
    if source_import:
        return [
            {
                'descricao': item.get('descricao') or item.get('codigo') or '',
                'quantidade': item.get('quantidade') or 1,
                'valor_unitario': item.get('valor_unitario') or 0,
                'cfop': item.get('cfop') or '5102',
                'ncm': item.get('ncm') or '',
                'unidade': item.get('unidade') or 'UN',
            }
            for item in source_import.get_items()
        ]
    if selected_product:
        imported_item = None
        if not selected_product.ncm or not selected_product.cfop:
            for imported in XmlInvoiceImport.query.order_by(XmlInvoiceImport.id.desc()).limit(PAGE_SIZE).all():
                imported_item = next((item for item in imported.get_items() if item.get('codigo') == selected_product.codigo), None)
                if imported_item:
                    break
        return [{
            'descricao': f'{selected_product.codigo} - {selected_product.nome}',
            'quantidade': 1,
            'valor_unitario': selected_product.preco_venda or 0,
            'cfop': selected_product.cfop or (imported_item or {}).get('cfop') or '5102',
            'ncm': selected_product.ncm or (imported_item or {}).get('ncm') or '',
            'unidade': selected_product.unidade or 'UN',
        }]
    return [{'descricao': '', 'quantidade': 1, 'valor_unitario': '', 'cfop': '5102', 'ncm': '', 'unidade': 'UN'}]


@web_bp.get('/os/<int:work_order_id>/nota/preview')
@login_required
@admin_required
def work_order_invoice_preview(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    config = get_fiscal_config()
    document_type = (request.args.get('tipo') or '').upper() or ('NFSE' if any(item.item_type == 'SERVICO' for item in order.items) else 'NFE')
    document = FiscalDocument.query.filter_by(work_order_id=order.id, document_type=document_type).order_by(FiscalDocument.id.desc()).first()
    payload = build_work_order_invoice_payload(order, config, document_type)
    if document and document.status in {'PRONTO_PARA_ENVIO', 'ERRO'} and document.request_payload:
        stored_payload = json.loads(document.request_payload)
        if stored_payload.get('customer'):
            payload = stored_payload
    template = 'fiscal/service_invoice.html' if document_type == 'NFSE' else 'fiscal/issue_preview.html'
    clients = Client.query.order_by(Client.nome.asc()).all()
    employees = Employee.query.filter_by(ativo=True).order_by(Employee.nome.asc()).all()
    return render_template(template, order=order, payload=payload, config=config, document=document, clients=clients, employees=employees)


@web_bp.post('/os/<int:work_order_id>/nota/preparar')
@login_required
@admin_required
def work_order_invoice_prepare(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    config = get_fiscal_config()
    document_type = (request.args.get('tipo') or request.form.get('tipo') or '').upper() or ('NFSE' if any(item.item_type == 'SERVICO' for item in order.items) else 'NFE')
    document = create_or_update_fiscal_document(order, config, document_type)
    db.session.commit()
    flash('Prévia fiscal gerada. Revise os dados antes de emitir.', 'success')
    return redirect(url_for('web.work_order_invoice_preview', work_order_id=order.id, tipo=document_type))


@web_bp.post('/os/<int:work_order_id>/nota/salvar-dados')
@login_required
@admin_required
def work_order_invoice_save_data(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    config = get_fiscal_config()
    document_type = (request.args.get('tipo') or request.form.get('tipo') or '').upper() or 'NFE'
    document = FiscalDocument.query.filter_by(work_order_id=order.id, document_type=document_type).order_by(FiscalDocument.id.desc()).first()
    if not document:
        document = create_or_update_fiscal_document(order, config, document_type)
    apply_invoice_form(document, request.form)
    db.session.commit()
    flash('Dados variáveis da nota salvos.', 'success')
    return redirect(url_for('web.work_order_invoice_preview', work_order_id=order.id, tipo=document_type))


@web_bp.post('/os/<int:work_order_id>/nota/emitir')
@login_required
@admin_required
def work_order_invoice_issue(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    config = get_fiscal_config()
    document = None
    document_id = None
    document_type = (request.args.get('tipo') or request.form.get('tipo') or '').upper() or ('NFSE' if any(item.item_type == 'SERVICO' for item in order.items) else 'NFE')
    if not config:
        flash('Configure a integração fiscal antes de emitir.', 'error')
        return redirect(url_for('web.work_order_invoice_preview', work_order_id=work_order_id, tipo=document_type))
    try:
        document = FiscalDocument.query.filter_by(work_order_id=order.id, document_type=document_type).order_by(FiscalDocument.id.desc()).first()
        if not document or document.status not in {'PRONTO_PARA_ENVIO', 'ERRO'}:
            document = create_or_update_fiscal_document(order, config, document_type)
        document_id = document.id
        if request.form.get('natureza_operacao') or request.form.get('item_lista_servico'):
            apply_invoice_form(document, request.form)
        db.session.commit()
        issue_with_external_api(document, config)
        db.session.commit()
        if document.status == 'ERRO':
            flash(f'Emissão recusada: {document.error_message or "verifique o documento fiscal"}', 'error')
        else:
            flash('Documento fiscal enviado para a API configurada.', 'success')
    except Exception as exc:
        db.session.rollback()
        if document_id:
            failed_document = db.session.get(FiscalDocument, document_id)
            if failed_document:
                failed_document.status = 'ERRO'
                failed_document.error_message = str(exc)
                db.session.commit()
        flash(f'Falha ao emitir nota: {exc}', 'error')
    return redirect(url_for('web.work_order_invoice_preview', work_order_id=work_order_id, tipo=document_type))


@web_bp.get('/fiscal/documentos/<int:document_id>/xml')
@login_required
@admin_required
def fiscal_document_export_xml(document_id: int):
    document = db.session.get(FiscalDocument, document_id)
    if not document or not document.xml_content:
        flash('XML fiscal não disponível.', 'error')
        return redirect(url_for('web.fiscal_index'))
    return send_file(
        io.BytesIO(document.xml_content.encode('utf-8')),
        mimetype='application/xml',
        as_attachment=True,
        download_name=f'{document.numero or document.id}.xml',
    )


@web_bp.post('/fiscal/documentos/<int:document_id>/consultar')
@login_required
@admin_required
def fiscal_document_consult(document_id: int):
    document = db.session.get(FiscalDocument, document_id)
    config = get_fiscal_config()
    if not document or not config or document.provider_name not in {'FOCUSNFE', 'UNINFE'}:
        flash('Documento ou integração fiscal não disponível.', 'error')
        return redirect(url_for('web.fiscal_index'))
    if current_app.config.get('ASYNC_EXTERNAL_CALLS'):
        from .jobs import enqueue
        enqueue('FISCAL_CONSULTAR', {'document_id': document.id})
        db.session.commit()
        flash('Consulta adicionada à fila fiscal.', 'success')
        return redirect(url_for('web.fiscal_index'))
    try:
        if document.provider_name == 'UNINFE':
            from .uninfe_dispatch import consult
            consult(document)
        else:
            consult_focus_nfse(document, config) if document.document_type == 'NFSE' else consult_focus_nfe(document, config)
        db.session.commit()
        flash(f'Status atualizado: {document.status}.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Falha ao consultar a nota: {exc}', 'error')
    return redirect(url_for('web.fiscal_index'))


@web_bp.post('/fiscal/documentos/<int:document_id>/emitir')
@login_required
@admin_required
def fiscal_document_issue(document_id: int):
    document = db.session.get(FiscalDocument, document_id)
    config = get_fiscal_config()
    if not document or not config:
        flash('Documento ou integração fiscal não disponível.', 'error')
        return redirect(url_for('web.fiscal_index'))
    if current_app.config.get('ASYNC_EXTERNAL_CALLS'):
        from .jobs import enqueue
        enqueue('FISCAL_EMITIR', {'document_id': document.id})
        document.status = 'NA_FILA'
        db.session.commit()
        flash('Emissão adicionada à fila fiscal.', 'success')
        return redirect(url_for('web.fiscal_index'))
    try:
        issue_with_external_api(document, config)
        db.session.commit()
        if document.status == 'ERRO':
            flash(f'Emissão recusada: {document.error_message or "verifique o documento fiscal"}', 'error')
        else:
            flash(f'Nota encaminhada. Status: {document.status}.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Falha ao emitir a nota: {exc}', 'error')
    return redirect(url_for('web.fiscal_index'))


@web_bp.route('/fiscal/documentos/<int:document_id>/cancelar', methods=['POST'])
@login_required
@admin_required
def fiscal_document_cancel(document_id: int):
    document = db.session.get(FiscalDocument, document_id)
    origem = request.args.get('origem', 'configuracoes')
    
    if not document:
        flash('Documento não encontrado.', 'error')
        if origem == 'financeiro':
            return redirect(url_for('web.finance_index'))
        return redirect(url_for('web.settings_index') + '#fiscal-documentos')
    
    config = get_fiscal_config()
    if not config or config.provider_name not in {'FOCUSNFE', 'UNINFE'}:
        flash('Integração fiscal não disponível.', 'error')
        if origem == 'financeiro':
            return redirect(url_for('web.finance_index'))
        return redirect(url_for('web.settings_index') + '#fiscal-documentos')
        
    try:
        justificativa = request.form.get('justificativa') or 'Cancelamento solicitado pelo usuario'
        if document.provider_name == 'UNINFE':
            from .uninfe_events import cancel
            cancel(document.id, request.form.get('justificativa') or '')
        elif document.document_type == 'NFSE':
            from .fiscal import cancel_focus_nfse
            cancel_focus_nfse(document, config, justificativa)
        else:
            from .fiscal import cancel_focus_nfe
            cancel_focus_nfe(document, config, justificativa)
        db.session.commit()
        flash('Nota cancelada com sucesso.' if document.status == 'CANCELADO' else 'Pedido de cancelamento encaminhado. Consulte o retorno para confirmar.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Falha ao cancelar a nota: {exc}', 'error')
        
    # Retorna para a aba exata do Financeiro (NF-e ou NFS-e)
    if origem == 'financeiro':
        return redirect(url_for('web.finance_index') + ('#nfse' if document.document_type == 'NFSE' else '#nfe'))
    return redirect(url_for('web.settings_index') + '#fiscal-documentos')

@web_bp.get('/formas-pagamento')
@login_required
@admin_required
def payment_methods_index():
    page = paginate_query(PaymentMethod.query.order_by(PaymentMethod.nome))
    return render_template('formas_pagamento/index.html', methods=page['items'], pagination=page)


@web_bp.route('/formas-pagamento/nova', methods=['GET', 'POST'])
@login_required
@admin_required
def payment_methods_new():
    if request.method == 'POST':
        method = PaymentMethod()
        _fill_payment_method_from_form(method)
        db.session.add(method)
        db.session.commit()
        flash('Forma de pagamento cadastrada.', 'success')
        return redirect(url_for('web.payment_methods_index'))
    return render_template('formas_pagamento/form.html', method=None)


@web_bp.route('/formas-pagamento/<int:method_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def payment_methods_edit(method_id: int):
    method = db.session.get(PaymentMethod, method_id)
    if not method:
        return redirect(url_for('web.payment_methods_index'))
    if request.method == 'POST':
        _fill_payment_method_from_form(method)
        db.session.commit()
        flash('Forma de pagamento atualizada.', 'success')
        return redirect(url_for('web.payment_methods_index'))
    return render_template('formas_pagamento/form.html', method=method)

@web_bp.post('/formas-pagamento/<int:method_id>/excluir')
@login_required
@admin_required
def payment_methods_delete(method_id: int):
    method = db.session.get(PaymentMethod, method_id)
    if not method:
        return redirect(url_for('web.payment_methods_index'))
    
    try:
        db.session.delete(method)
        db.session.commit()
        flash('Forma de pagamento excluída.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Esta forma de pagamento não pode ser excluída pois já possui vínculos no sistema (ex: Ordens de Serviço ou Financeiro). Experimente apenas inativá-la na edição.', 'error')
        
    return redirect(url_for('web.payment_methods_index'))

@web_bp.post('/os/<int:work_order_id>/excluir')
@login_required
@admin_required
def work_orders_delete(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    
    entradas_fin = FinancialEntry.query.filter_by(reference_type='OS', reference_id=order.id).all()
    if any(entrada.status in ('RECEBIDO', 'PAGO') for entrada in entradas_fin):
        # Apagar um recebimento já liquidado deixaria o saldo bancário sem lançamento correspondente.
        flash('Esta O.S. tem recebimentos liquidados. Estorne-os no Financeiro antes de excluir.', 'error')
        return redirect(url_for('web.work_orders_show', work_order_id=order.id))
    for entrada in entradas_fin:
        db.session.delete(entrada)
        
    db.session.delete(order)
    db.session.commit()
    flash('Ordem de serviço excluída com sucesso.', 'success')
    return redirect(url_for('web.work_orders_index'))

@web_bp.post('/clientes/<int:client_id>/excluir')
@login_required
@admin_required
def clients_delete(client_id: int):
    client = db.session.get(Client, client_id)
    if not client:
        return redirect(url_for('web.clients_index'))
        
    from .fleet.models import VehicleOwnershipHistory
    ownership = VehicleOwnershipHistory.query.filter(db.or_(
        VehicleOwnershipHistory.client_id == client.id,
        VehicleOwnershipHistory.previous_client_id == client.id,
    )).first()
    if client.vehicles or ownership:
        flash('Não é possível excluir: cliente vinculado ao cadastro ou histórico de veículos.', 'error')
        return redirect(url_for('web.clients_index'))
    if client.work_orders or client.budgets:
        flash('Não é possível excluir: Cliente possui Ordens de Serviço ou Orçamentos vinculados.', 'error')
        return redirect(url_for('web.clients_index'))
        
    db.session.delete(client)
    db.session.commit()
    flash('Cliente excluído com sucesso.', 'success')
    return redirect(url_for('web.clients_index'))

@web_bp.post('/financeiro/<int:entry_id>/estornar')
@login_required
@admin_required
def finance_revert(entry_id: int):
    entry = db.session.get(FinancialEntry, entry_id)
    if not entry:
        return redirect(url_for('web.finance_index'))
        
    if entry.status in ['RECEBIDO', 'PAGO']:
        # Estorna o saldo da conta bancária — usa o valor líquido que foi creditado/debitado
        if entry.bank_account_id:
            account = db.session.get(BankAccount, entry.bank_account_id)
            if account:
                # Calcula o valor líquido que foi movimentado na liquidação
                valor_baixa = parse_decimal(entry.valor_baixa) if entry.valor_baixa is not None else parse_decimal(entry.valor)
                juros = parse_decimal(entry.juros)
                desconto = parse_decimal(entry.desconto)
                taxa = parse_decimal(entry.taxa)
                acrescimo = parse_decimal(entry.acrescimo)
                valor_liquido = valor_baixa + juros - desconto - taxa + acrescimo
                if entry.entry_type == 'RECEBER':
                    account.saldo_atual = parse_decimal(account.saldo_atual) - valor_liquido
                else:
                    account.saldo_atual = parse_decimal(account.saldo_atual) + valor_liquido
                    
        # Reverte o lançamento para pendente e limpa campos de liquidação
        entry.status = 'PENDENTE'
        entry.payment_receipt_at = None
        entry.valor_baixa = None
        entry.juros = None
        entry.desconto = None
        entry.taxa = None
        entry.acrescimo = None
        entry.observacoes_pagamento = None
        db.session.commit()
        flash('Lançamento estornado e saldo revertido com sucesso.', 'success')
    else:
        flash('Apenas lançamentos liquidados podem ser estornados.', 'error')
        
    return redirect(url_for('web.finance_index'))

@web_bp.post('/financeiro/<int:entry_id>/remover')
@login_required
@admin_required
def finance_delete(entry_id: int):
    entry = db.session.get(FinancialEntry, entry_id)
    if not entry:
        return redirect(url_for('web.finance_index'))
        
    # Se o lançamento estava liquidado, reverte o saldo da conta bancária antes de apagar
    if entry.status in ['RECEBIDO', 'PAGO'] and entry.bank_account_id:
        account = db.session.get(BankAccount, entry.bank_account_id)
        if account:
            valor_baixa = parse_decimal(entry.valor_baixa) if entry.valor_baixa is not None else parse_decimal(entry.valor)
            juros = parse_decimal(entry.juros)
            desconto = parse_decimal(entry.desconto)
            taxa = parse_decimal(entry.taxa)
            acrescimo = parse_decimal(entry.acrescimo)
            valor_liquido = valor_baixa + juros - desconto - taxa + acrescimo
            if entry.entry_type == 'RECEBER':
                account.saldo_atual = parse_decimal(account.saldo_atual) - valor_liquido
            else:
                account.saldo_atual = parse_decimal(account.saldo_atual) + valor_liquido
                
    db.session.delete(entry)
    db.session.commit()
    flash('Lançamento financeiro removido com sucesso.', 'success')
    return redirect(url_for('web.finance_index'))

@web_bp.get('/funcionarios')
@login_required
@admin_required
def employees_index():
    page = paginate_query(Employee.query.order_by(Employee.nome))
    return render_template('funcionarios/index.html', employees=page['items'], pagination=page)


@web_bp.route('/funcionarios/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def employees_new():
    if request.method == 'POST':
        employee = Employee()
        _fill_employee_from_form(employee)
        db.session.add(employee)
        db.session.commit()
        flash('Funcionário cadastrado.', 'success')
        return redirect(url_for('web.employees_index'))
    return render_template('funcionarios/form.html', employee=None)

@web_bp.route('/funcionarios/<int:employee_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def employees_edit(employee_id: int):
    employee = db.session.get(Employee, employee_id)
    if not employee:
        return redirect(url_for('web.employees_index'))
    if request.method == 'POST':
        _fill_employee_from_form(employee)
        db.session.commit()
        flash('Funcionário atualizado.', 'success')
        return redirect(url_for('web.employees_index'))
    return render_template('funcionarios/form.html', employee=employee)

@web_bp.route('/fiscal/documentos/<int:document_id>/excluir', methods=['POST'])
@login_required
@admin_required
def fiscal_document_delete(document_id: int):
    document = db.session.get(FiscalDocument, document_id)
    origem = request.args.get('origem', 'configuracoes')
    
    if not document:
        flash('Documento não encontrado.', 'error')
        if origem == 'financeiro':
            return redirect(url_for('web.finance_index'))
        return redirect(url_for('web.settings_index') + '#fiscal-documentos')
    
    # Nova trava: só impede de excluir se estiver de fato na Sefaz/Prefeitura
    if document.status in ['AUTORIZADO', 'PROCESSANDO_AUTORIZACAO', 'ENVIADO']:
        flash('Não é possível excluir um documento enviado à Sefaz. Utilize a opção Cancelar.', 'error')
        if origem == 'financeiro':
            return redirect(url_for('web.finance_index') + ('#nfse' if document.document_type == 'NFSE' else '#nfe'))
        return redirect(url_for('web.settings_index') + '#fiscal-documentos')
        
    doc_type = document.document_type
    db.session.delete(document)
    db.session.commit()
    flash('Documento excluído do sistema com sucesso.', 'success')
    
    if origem == 'financeiro':
        return redirect(url_for('web.finance_index') + ('#nfse' if doc_type == 'NFSE' else '#nfe'))
    return redirect(url_for('web.settings_index') + '#fiscal-documentos')


def _settings_prefix(value: str | None, fallback: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9-]', '', value or '').upper()[:10]
    return cleaned or fallback


def _settings_positive_int(value: str | None, fallback: int) -> int:
    try:
        return max(int(value or fallback), 0)
    except (TypeError, ValueError):
        return fallback


def _decimal_input_value(value, fallback: str = '0.00') -> str:
    if value in (None, ''):
        return fallback
    return f"{parse_decimal(value):.2f}"


def _item_rows_for_template(order: WorkOrder | None, prefix: str, item_type: str) -> list[dict]:
    if request.method == 'POST':
        descricoes = request.form.getlist(f'{prefix}_descricao[]')
        quantidades = request.form.getlist(f'{prefix}_quantidade[]')
        valores = request.form.getlist(f'{prefix}_valor_unitario[]')
        totais = request.form.getlist(f'{prefix}_total[]')
        rows: list[dict] = []
        total_rows = max(len(descricoes), len(quantidades), len(valores), len(totais), 0)
        for index in range(total_rows):
            descricao = (descricoes[index] if index < len(descricoes) else '').strip()
            quantidade = quantidades[index] if index < len(quantidades) else ''
            valor_unitario = valores[index] if index < len(valores) else ''
            total = totais[index] if index < len(totais) else ''
            if not any([descricao, str(quantidade).strip(), str(valor_unitario).strip(), str(total).strip()]):
                continue
            rows.append(
                {
                    'descricao': descricao,
                    'quantidade': quantidade or '1.00',
                    'valor_unitario': valor_unitario or '0.00',
                    'total': total or '0.00',
                }
            )
        if rows:
            return rows

    if order:
        rows = [
            {
                'descricao': item.descricao,
                'quantidade': _decimal_input_value(item.quantidade, '1.00'),
                'valor_unitario': _decimal_input_value(item.valor_unitario),
                'total': _decimal_input_value(item.total),
            }
            for item in order.items
            if item.item_type == item_type
        ]
        if rows:
            return rows

    return []


def _extract_work_order_items_from_form(prefix: str, item_type: str) -> list[dict]:
    descricoes = request.form.getlist(f'{prefix}_descricao[]')
    quantidades = request.form.getlist(f'{prefix}_quantidade[]')
    valores = request.form.getlist(f'{prefix}_valor_unitario[]')
    totais = request.form.getlist(f'{prefix}_total[]')

    items: list[dict] = []
    total_rows = max(len(descricoes), len(quantidades), len(valores), len(totais), 0)
    for index in range(total_rows):
        descricao = (descricoes[index] if index < len(descricoes) else '').strip()
        quantidade = quantidades[index] if index < len(quantidades) else ''
        valor_unitario = valores[index] if index < len(valores) else ''
        total = totais[index] if index < len(totais) else ''

        if not any([descricao, str(quantidade).strip(), str(valor_unitario).strip(), str(total).strip()]):
            continue

        items.append(
            {
                'item_type': item_type,
                'descricao': descricao,
                'quantidade': quantidade or '1',
                'valor_unitario': valor_unitario or '0',
                'total': total or '',
            }
        )
    return items


def _sync_work_order_payments_from_form(order: WorkOrder) -> None:
    if current_user() and current_user().role != 'ADMINISTRADOR':
        return

    from .models import WorkOrderPayment, PaymentMethod
    from .utils import parse_decimal
    from decimal import Decimal
    
    methods = request.form.getlist('payment_method_id[]')
    values = request.form.getlist('payment_value[]')
    installments = request.form.getlist('payment_installments[]')

    if methods and len(methods) > 0 and methods[0]:
        order.payments.clear()
        
        for i in range(len(methods)):
            if not methods[i]:
                continue
            method_id = int(methods[i])
            val = parse_decimal(values[i]) if i < len(values) else Decimal('0')
            if val <= 0:
                continue
                
            inst = int(installments[i]) if i < len(installments) and installments[i] else 1
            
            method = db.session.get(PaymentMethod, method_id)
            if not method:
                continue
            if not method.permite_parcelamento:
                inst = 1
            else:
                max_inst = max(method.parcelas_maximas or 1, 1)
                inst = min(max(inst, 1), max_inst)
                
            payment = WorkOrderPayment(
                payment_method_id=method_id,
                valor=val,
                installment_count=inst
            )
            order.payments.append(payment)
        
        order.payment_method_id = None
        order.installment_count = 1


def _sync_work_order_items_from_form(order: WorkOrder) -> None:
    items_payload = _extract_work_order_items_from_form('servico', 'SERVICO')
    items_payload += _extract_work_order_items_from_form('peca', 'PECA')
    replace_work_order_items(order, items_payload)


def _render_work_order_form(order: WorkOrder | None):
    employees = Employee.query.filter_by(ativo=True).order_by(Employee.nome).all()
    payment_methods = PaymentMethod.query.filter_by(ativo=True).order_by(PaymentMethod.nome).all()
    return render_template(
        'os/form.html',
        order=order,
        employees=employees,
        payment_methods=payment_methods,
        statuses=WORK_ORDER_STATUSES,
        service_rows=_item_rows_for_template(order, 'servico', 'SERVICO'),
        product_rows=_item_rows_for_template(order, 'peca', 'PECA'),
    )


@web_bp.get('/os/catalogo')
@login_required
@permission_required('work_orders.manage')
def work_orders_catalog_lookup():
    """Services (tipo=SERVICO) or products matching q, with the price the O.S. form suggests."""
    model, price = (Service, 'preco_base') if request.args.get('tipo') == 'SERVICO' else (Product, 'preco_venda')
    query = model.query.filter_by(ativo=True)
    term = request.args.get('q', '').strip()
    if term:
        query = query.filter(model.nome.ilike(f'%{term}%'))
    return {'items': [{'nome': item.nome, 'preco': float(parse_decimal(getattr(item, price)))}
                      for item in query.order_by(model.nome).limit(20)]}


def _fill_client_from_form(client: Client) -> None:
    document = (request.form.get('cpf_cnpj') or '').strip()
    lookup_data = None
    if is_cnpj(document):
        try:
            lookup_data = lookup_cnpj(document)
        except Exception:
            lookup_data = None
    elif is_cpf(document) and request.form.get('autofill_document'):
        try:
            lookup_data = lookup_cpf(document)
        except Exception:
            lookup_data = None
    client.nome = request.form.get('nome', '').strip() or (lookup_data or {}).get('nome') or client.nome
    client.cpf_cnpj = document or None
    client.telefone = request.form.get('telefone') or (lookup_data or {}).get('telefone') or None
    client.email = request.form.get('email') or (lookup_data or {}).get('email') or None
    client.endereco = request.form.get('endereco') or (lookup_data or {}).get('endereco') or None
    client.observacoes = request.form.get('observacoes') or client.observacoes


def _fill_product_from_form(product: Product) -> None:
    product.codigo = request.form.get('codigo', '').strip().upper()
    product.nome = request.form.get('nome', '').strip().upper()
    product.categoria = request.form.get('categoria') or None
    product.marca = request.form.get('marca') or None
    product.unidade = request.form.get('unidade') or 'UN'
    product.ncm = request.form.get('ncm') or product.ncm
    product.cfop = request.form.get('cfop') or product.cfop
    product.custo = parse_decimal(request.form.get('custo'))
    product.preco_venda = parse_decimal(request.form.get('preco_venda'))
    product.estoque_atual = parse_decimal(request.form.get('estoque_atual'))
    product.estoque_minimo = parse_decimal(request.form.get('estoque_minimo'))
    product.ativo = bool(request.form.get('ativo'))


def _fill_service_from_form(service: Service) -> None:
    service.nome = request.form.get('nome', '').strip().upper()
    service.descricao = request.form.get('descricao') or None
    service.preco_base = parse_decimal(request.form.get('preco_base'))
    service.ativo = bool(request.form.get('ativo'))


def _fill_budget_from_form(budget: Budget) -> None:
    budget.client_id = int(request.form.get('client_id'))
    budget.placa = (request.form.get('placa') or '').upper() or None
    budget.veiculo_descricao = request.form.get('veiculo_descricao') or None
    budget.desconto = parse_decimal(request.form.get('desconto'))
    budget.validade = parse_date(request.form.get('validade')) or budget_default_date()
    budget.observacoes = request.form.get('observacoes') or None
    from .fleet.services import link_vehicle
    link_vehicle(budget, request.form)



def _resolve_or_create_client_for_work_order() -> Client:
    selected_id = request.form.get('client_id')
    typed_name = (request.form.get('client_nome') or '').strip()
    if selected_id:
        client = db.session.get(Client, int(selected_id))
        if not client:
            raise ValueError('Cliente selecionado não encontrado.')
        return client
    if not typed_name:
        raise ValueError('Informe o nome do cliente ou selecione um cadastro existente.')
    existing = Client.query.filter(db.func.lower(Client.nome) == typed_name.lower()).first()
    if existing:
        return existing
    client = Client(nome=typed_name)
    db.session.add(client)
    db.session.flush()
    return client


def _fill_work_order_from_form(order: WorkOrder) -> None:
    client = _resolve_or_create_client_for_work_order()
    order.client_id = client.id
    order.client_nome = (request.form.get('client_nome') or client.nome or '').strip() or client.nome
    order.employee_id = int(request.form.get('employee_id')) if request.form.get('employee_id') else None
    order.placa = (request.form.get('placa') or '').upper() or None
    order.veiculo_descricao = request.form.get('veiculo_descricao') or None
    order.data_entrada = parse_date(request.form.get('data_entrada'))
    order.observacoes = request.form.get('observacoes') or None
    for field in ('problema_relatado', 'laudo', 'observacoes_cliente'):
        setattr(order, field, (request.form.get(field) or '').strip() or None)
    tipo = request.form.get('tipo_atendimento') or None
    if tipo not in (None, 'INTERNO', 'EXTERNO', 'GARANTIA'):
        raise ValueError('Tipo de atendimento inválido.')
    order.tipo_atendimento = tipo
    promised = parse_date(request.form.get('promised_at'))
    if not promised:
        order.promised_at = None
    elif not order.promised_at or order.promised_at.date() != promised:  # mantém a hora vinda da agenda
        order.promised_at = datetime.combine(promised, time(18, 0))
    order.desconto = parse_decimal(request.form.get('desconto') or 0)
    order.emitir_nota = True
    from .fleet.services import link_vehicle
    link_vehicle(order, request.form)

    if current_user() and current_user().role == 'ADMINISTRADOR':
        order.payment_method_id = int(request.form.get('payment_method_id')) if request.form.get('payment_method_id') else None
        order.installment_count = _normalized_installments(order.payment_method_id, request.form.get('installment_count'))
    elif not order.installment_count:
        order.installment_count = 1


def _fill_employee_from_form(employee: Employee) -> None:
    employee.nome = request.form.get('nome', '').strip()
    employee.funcao = request.form.get('funcao', '').strip()
    employee.telefone = request.form.get('telefone') or None
    employee.email = request.form.get('email') or None
    employee.observacoes = request.form.get('observacoes') or None
    employee.ativo = bool(request.form.get('ativo'))


def _fill_payment_method_from_form(method: PaymentMethod) -> None:
    method.nome = request.form.get('nome', '').strip()
    method.tipo = request.form.get('tipo') or 'OUTRO'
    method.ativo = bool(request.form.get('ativo'))
    method.permite_parcelamento = bool(request.form.get('permite_parcelamento')) if method.tipo == 'CREDITO' else False
    method.parcelas_maximas = int(request.form.get('parcelas_maximas') or 1) if method.tipo == 'CREDITO' else 1


def _normalized_installments(payment_method_id, raw_value) -> int:
    if not payment_method_id:
        return 1
    method = db.session.get(PaymentMethod, int(payment_method_id))
    if not method or not method.permite_parcelamento:
        return 1
    max_installments = max(method.parcelas_maximas or 1, 1)
    installments = max(int(raw_value or 1), 1)
    return min(installments, max_installments)


def _resolve_item_payload(source) -> tuple[str, int]:
    item_type = (source.get('item_type') or '').upper()
    if item_type == 'SERVICO':
        reference_id = source.get('service_id') or source.get('reference_id')
        normalized_type = 'SERVICO'
    elif item_type in {'PRODUTO', 'PECA'}:
        reference_id = source.get('product_id') or source.get('part_id') or source.get('reference_id')
        normalized_type = 'PECA'
    else:
        raise ValueError('Tipo de item inválido.')
    if not reference_id:
        raise ValueError('Selecione um item do catálogo.')
    return normalized_type, int(reference_id)


@web_bp.post('/produtos/<int:product_id>/excluir')
@login_required
@admin_required
def products_delete(product_id):
    produto = db.session.get(Product, product_id)
    if not produto:
        flash('Produto não encontrado.', 'error')
        return redirect(url_for('web.products_index'))
    
    produto.ativo = False
    db.session.commit()
    flash('Produto inativado com sucesso.', 'success')
    return redirect(url_for('web.products_index'))

@web_bp.post('/servicos/<int:service_id>/excluir')
@login_required
@admin_required
def services_delete(service_id):
    servico = db.session.get(Service, service_id)
    if not servico:
        flash('Serviço não encontrado.', 'error')
        return redirect(url_for('web.services_index'))
    
    servico.ativo = False
    db.session.commit()
    flash('Serviço inativado com sucesso.', 'success')
    return redirect(url_for('web.services_index'))


@web_bp.route('/relatorios')
@login_required
@admin_required
def reports_index():
    from datetime import datetime, date, timedelta
    from sqlalchemy import func
    from decimal import Decimal
    
    # Filtros
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    date_type = request.args.get('date_type', 'data_entrada')
    client_id = request.args.get('client_id')
    employee_id = request.args.get('employee_id')
    placa = request.args.get('placa', '').strip()
    status_filter = [value for value in request.args.getlist('status') if value]
    if not status_filter or 'FECHADAS' in status_filter:  # padrão do relatório de faturamento
        status_filter = ['FINALIZADA', 'ENTREGUE']
    show_items = request.args.get('show_items', 'both')
    is_faturada = request.args.get('is_faturada', '')
    
    today = date.today()
    if not start_date_str:
        start_date = today.replace(day=1)
    else:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
    if not end_date_str:
        end_date = today
    else:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
    query = WorkOrder.query
    
    if date_type == 'data_saida':
        query = query.filter(WorkOrder.data_saida >= start_date, WorkOrder.data_saida <= end_date)
    else:
        query = query.filter(WorkOrder.data_entrada >= start_date, WorkOrder.data_entrada <= end_date)
        
    if client_id:
        query = query.filter(WorkOrder.client_id == client_id)
    if employee_id:
        query = query.filter(WorkOrder.employee_id == employee_id)
    if placa:
        query = query.filter(WorkOrder.placa.ilike(f'%{placa}%'))
    if status_filter and 'TODOS' not in status_filter:
        query = query.filter(WorkOrder.status.in_(status_filter))
        
    orders_raw = query.order_by(WorkOrder.data_entrada.desc()).all()
    
    # Process orders based on show_items and faturada
    orders = []
    total_servicos = Decimal('0')
    total_pecas = Decimal('0')
    total_desconto = Decimal('0')
    total_geral = Decimal('0')
    
    for order in orders_raw:
        has_payments = len(order.payments) > 0
        if is_faturada == 'S' and not has_payments:
            continue
        if is_faturada == 'N' and has_payments:
            continue
            
        filtered_items = []
        for item in order.items:
            if show_items == 'pecas' and item.item_type != 'PECA':
                continue
            if show_items == 'servicos' and item.item_type != 'SERVICO':
                continue
            filtered_items.append(item)
            
        if show_items != 'both' and not filtered_items and len(order.items) > 0:
            continue
            
        order.filtered_items = filtered_items
        
        o_servicos = sum([i.total for i in filtered_items if i.item_type == 'SERVICO'])
        o_pecas = sum([i.total for i in filtered_items if i.item_type == 'PECA'])
        o_desconto = sum([i.desconto for i in filtered_items])
        o_total = o_servicos + o_pecas

        if not order.items:
            o_servicos = (order.total_servicos or Decimal('0')) if show_items != 'pecas' else Decimal('0')
            o_pecas = (order.total_pecas or Decimal('0')) if show_items != 'servicos' else Decimal('0')
            o_desconto = max(Decimal('0'), (order.total_servicos or Decimal('0')) +
                (order.total_pecas or Decimal('0')) - (order.total_geral or Decimal('0'))) if show_items == 'both' else Decimal('0')
            o_total = (order.total_geral or Decimal('0')) if show_items == 'both' else o_servicos + o_pecas
        
        order.calc_servicos = o_servicos
        order.calc_pecas = o_pecas
        order.calc_desconto = o_desconto
        order.calc_total = o_total
        
        total_servicos += o_servicos
        total_pecas += o_pecas
        total_desconto += o_desconto
        total_geral += o_total
        
        orders.append(order)
        
    selected_client = db.session.get(Client, int(client_id)) if client_id and client_id.isdigit() else None
    employees = Employee.query.order_by(Employee.nome).all()
        
    return render_template('relatorios/index.html',
                           orders=orders,
                           start_date=start_date,
                           end_date=end_date,
                           date_type=date_type,
                           status_filter=status_filter,
                           client_id=int(client_id) if client_id else '',
                           employee_id=int(employee_id) if employee_id else '',
                           placa=placa,
                           show_items=show_items,
                           is_faturada=is_faturada,
                           total_servicos=total_servicos,
                           total_pecas=total_pecas,
                           total_desconto=total_desconto,
                           total_geral=total_geral,
                           selected_client=selected_client,
                           employees=employees)



@web_bp.post('/configuracoes/usuarios/<int:user_id>/excluir')
@login_required
@admin_required
def settings_users_delete(user_id: int):
    if user_id == current_user().id:
        flash('Você não pode excluir a si mesmo.', 'error')
        return redirect(url_for('web.settings_index') + '#acessos')
        
    user = db.session.get(User, user_id)
    if not user:
        return redirect(url_for('web.settings_index') + '#acessos')
        
    if user.role == 'ADMINISTRADOR' and User.query.filter_by(role='ADMINISTRADOR').count() <= 1:
        flash('Mantenha pelo menos um administrador no sistema.', 'error')
        return redirect(url_for('web.settings_index') + '#acessos')
        
    db.session.delete(user)
    db.session.commit()
    flash('Usuário excluído com sucesso.', 'success')
    return redirect(url_for('web.settings_index') + '#acessos')


@web_bp.post('/funcionarios/<int:employee_id>/excluir')
@login_required
@admin_required
def employees_delete(employee_id: int):
    employee = db.session.get(Employee, employee_id)
    if not employee:
        return redirect(url_for('web.employees_index'))
        
    if employee.work_orders:
        flash('Não é possível excluir o funcionário pois ele possui Ordens de Serviço vinculadas. Considere inativá-lo editando o cadastro.', 'error')
        return redirect(url_for('web.employees_index'))
        
    db.session.delete(employee)
    db.session.commit()
    flash('Funcionário excluído.', 'success')
    return redirect(url_for('web.employees_index'))


@web_bp.route('/relatorios/exportar-xml', methods=['GET'])
@login_required
@admin_required
def reports_export_xml():
    import io
    import zipfile
    from datetime import datetime
    
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    client_id = request.args.get('client_id')
    
    if not start_date_str or not end_date_str:
        flash('Datas inicial e final so obrigatrias para exportar XML.', 'error')
        return redirect(url_for('web.fiscal_index'))
        
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    
    query = FiscalDocument.query.filter(
        FiscalDocument.xml_content.isnot(None)
    )
    
    if client_id:
        query = query.join(WorkOrder).filter(WorkOrder.client_id == client_id)
        
    docs = query.all()
    # Ps filtro de data por segurana
    docs = [d for d in docs if d.created_at and start_date <= d.created_at.date() <= end_date]
    if not docs:
        flash('Nenhum XML encontrado para os filtros selecionados.', 'warning')
        return redirect(url_for('web.fiscal_index'))
        
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            content_bytes = doc.xml_content.encode('utf-8') if isinstance(doc.xml_content, str) else doc.xml_content
            filename = f'NF_{doc.document_type}_{doc.numero or doc.id}.xml'
            zf.writestr(filename, content_bytes)
            
    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'NotasFiscais_{start_date_str}_ate_{end_date_str}.zip'
    )



