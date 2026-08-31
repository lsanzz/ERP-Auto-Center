from __future__ import annotations

from sqlalchemy.orm import joinedload
from collections import OrderedDict
import base64
import io
import json
import re
from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from decimal import Decimal

from .auth import admin_required, current_user, login_required, login_user, logout_user
from .cep import lookup_cep
from .cnpj import is_cnpj, is_cpf, lookup_cnpj, lookup_cpf
from .models import BankAccount, Budget, Client, Employee, FinancialEntry, FiscalApiConfig, FiscalDocument, PaymentMethod, Product, Service, User, WorkOrder, WorkOrderItem, XmlInvoiceImport, db
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
    next_number,
    recalculate_budget_totals,
    recalculate_work_order_totals,
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
    save_fiscal_config_from_form,
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


@web_bp.get('/')
def root():
    return redirect(url_for('web.dashboard' if current_user() else 'web.login'))


@web_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user():
        return redirect(url_for('web.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, ativo=True).first()
        if user and user.check_password(password):
            login_user(user)
            flash('Login realizado com sucesso.', 'success')
            return redirect(request.args.get('next') or url_for('web.dashboard'))
        flash('Usuário ou senha inválidos.', 'error')

    return render_template('auth/login.html')


@web_bp.get('/logout')
@login_required
def logout():
    logout_user()
    flash('Sessão encerrada.', 'success')
    return redirect(url_for('web.login'))


@web_bp.get('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard/index.html', data=dashboard_data(current_user().role), bank_accounts=BankAccount.query.order_by(BankAccount.nome).all() if current_user().role == 'ADMINISTRADOR' else [])


@web_bp.get('/consultas/placa')
@login_required
def plate_lookup_page():
    return render_template('consultas/placa.html')


@web_bp.route('/configuracoes', methods=['GET'])
@login_required
@admin_required
def settings_index():
    fiscal_documents_page = paginate_query(FiscalDocument.query.order_by(FiscalDocument.id.desc()))
    users_page = paginate_query(User.query.order_by(User.nome))
    return render_template(
        'configuracoes/index.html',
        settings=get_system_settings(),
        fiscal_config=FiscalApiConfig.query.order_by(FiscalApiConfig.id.asc()).first(),
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
    if settings.id is None:
        db.session.add(settings)
    settings.company_name = request.form.get('company_name', '').strip() or 'Japa Auto Center'
    settings.trade_name = request.form.get('trade_name') or None
    settings.company_document = request.form.get('company_document') or None
    settings.phone = request.form.get('phone') or None
    settings.email = request.form.get('email') or None
    settings.address = request.form.get('address') or None
    settings.city = request.form.get('city') or None
    settings.state = (request.form.get('state') or '').strip().upper()[:2] or None
    settings.zip_code = request.form.get('zip_code') or None
    db.session.commit()
    flash('Dados da empresa atualizados.', 'success')
    return redirect(url_for('web.settings_index'))


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
        if len(new_password) < 6:
            flash('A nova senha deve ter pelo menos 6 caracteres.', 'error')
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
        role = request.form.get('role') if request.form.get('role') in {'ADMINISTRADOR', 'MECANICO'} else 'MECANICO'
        if not username or len(password) < 6:
            flash('Informe usuário e uma senha com pelo menos 6 caracteres.', 'error')
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
        role = request.form.get('role') if request.form.get('role') in {'ADMINISTRADOR', 'MECANICO'} else 'MECANICO'
        if duplicate:
            flash('Este usuário já existe.', 'error')
        elif not username or (password and len(password) < 6):
            flash('Usuário inválido ou senha menor que 6 caracteres.', 'error')
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
    db.session.delete(account)
    db.session.commit()
    flash('Conta bancária removida.', 'success')
    return redirect(url_for('web.dashboard'))

@web_bp.route('/clientes')
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


@web_bp.get('/api/cep/<cep>')
@login_required
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
        _fill_product_from_form(product)
        db.session.commit()
        flash('Peça atualizada.', 'success')
        return redirect(url_for('web.products_index'))
    return render_template('produtos/form.html', product=product)

@web_bp.post('/produtos/importar-xml')
@login_required
@admin_required
def products_import_xml():
    upload = request.files.get('xml_file')
    if not upload or not upload.filename:
        flash('Selecione um arquivo XML.', 'error')
        return redirect(url_for('web.products_index'))
        
    try:
        raw_xml = upload.read()
        parsed = parse_nfe_xml(raw_xml)
        
        novos = 0
        atualizados = 0
        
        for item in parsed.get('itens', []):
            # Tenta encontrar a peça pelo código original do fornecedor
            product = Product.query.filter_by(codigo=item['codigo']).first()
            
            custo_unitario = parse_decimal(item['valor_unitario'])
            
            if product:
                # Se a peça já existe, apenas atualiza o custo
                product.custo = custo_unitario
                product.ncm = item.get('ncm') or product.ncm
                product.cfop = item.get('cfop') or product.cfop
                product.estoque_atual = parse_decimal(product.estoque_atual) + parse_decimal(item.get('quantidade'))
                atualizados += 1
            else:
                # Se não existe, cria a nova peça
                product = Product(
                    codigo=item['codigo'],
                    nome=item['descricao'],
                    unidade=item['unidade'],
                    custo=custo_unitario,
                    # Adicionando uma margem de lucro padrão inicial (ex: 50%)
                    preco_venda=custo_unitario * Decimal('1.5'),
                    estoque_atual=parse_decimal(item.get('quantidade')),
                    ncm=item.get('ncm'),
                    cfop=item.get('cfop'),
                    ativo=True
                )
                db.session.add(product)
                novos += 1
                
        db.session.commit()
        flash(f'XML Importado com sucesso! {novos} peças adicionadas e {atualizados} peças atualizadas (custo).', 'success')
        
    except Exception as exc:
        db.session.rollback()
        flash(f'Falha ao importar peças pelo XML: {exc}', 'error')
        
    return redirect(url_for('web.products_index'))

@web_bp.post('/produtos/importar-xml/preview')
@login_required
@admin_required
def products_import_xml_preview():
    upload = request.files.get('xml_file')
    if not upload or not upload.filename:
        flash('Selecione um arquivo XML.', 'error')
        return redirect(url_for('web.products_index'))

    try:
        raw_xml = upload.read()
        parsed = parse_nfe_xml(raw_xml)
        
        # Verificar se o fornecedor já existe
        fornecedor = Client.query.filter_by(cpf_cnpj=parsed.get('emitente_cnpj')).first()
        parsed['fornecedor_cadastrado'] = 'Sim' if fornecedor else 'Não'

        for item in parsed.get('itens', []):
            existing = Product.query.filter_by(codigo=item['codigo']).first()
            item['exists'] = bool(existing)
            if existing:
                item['nome_sugerido'] = existing.nome
                item['margem_sugerida'] = 0 
                item['preco_venda_sugerido'] = float(existing.preco_venda)
            else:
                item['nome_sugerido'] = item['descricao']
                item['margem_sugerida'] = 50.0
                item['preco_venda_sugerido'] = float(item['valor_unitario']) * 1.5

        # Envia o XML cru encodado para podermos ler depois na confirmação
        raw_xml_b64 = base64.b64encode(raw_xml).decode('ascii')

        return render_template(
            'produtos/xml_preview.html',
            parsed=parsed,
            raw_xml_b64=raw_xml_b64
        )
    except Exception as exc:
        flash(f'Falha ao ler XML: {exc}', 'error')
        return redirect(url_for('web.products_index'))


@web_bp.post('/produtos/importar-xml/confirmar')
@login_required
@admin_required
def products_import_xml_confirm():
    codigos = request.form.getlist('codigo[]')
    nomes = request.form.getlist('nome[]')
    unidades = request.form.getlist('unidade[]')
    custos = request.form.getlist('custo[]')
    precos_venda = request.form.getlist('preco_venda[]')
    importar_flags = request.form.getlist('importar[]')
    
    raw_xml_b64 = request.form.get('raw_xml_b64')

    novos = 0
    atualizados = 0

    try:
        raw_xml = base64.b64decode(raw_xml_b64.encode('ascii')) if raw_xml_b64 else b''
        parsed = parse_nfe_xml(raw_xml) if raw_xml else {'itens': []}
        # 1. Salva os produtos no catálogo
        for idx, codigo in enumerate(codigos):
            if codigo not in importar_flags:
                continue 

            product = Product.query.filter_by(codigo=codigo).first()
            custo_val = parse_decimal(custos[idx])
            venda_val = parse_decimal(precos_venda[idx])

            if product:
                product.nome = nomes[idx]
                product.unidade = unidades[idx]
                product.custo = custo_val
                product.preco_venda = venda_val
                product.ncm = parsed['itens'][idx].get('ncm') or product.ncm
                product.cfop = parsed['itens'][idx].get('cfop') or product.cfop
                product.estoque_atual = parse_decimal(product.estoque_atual) + parse_decimal(parsed['itens'][idx].get('quantidade'))
                atualizados += 1
            else:
                product = Product(
                    codigo=codigo,
                    nome=nomes[idx],
                    unidade=unidades[idx],
                    custo=custo_val,
                    preco_venda=venda_val,
                    estoque_atual=parse_decimal(parsed['itens'][idx].get('quantidade')),
                    ncm=parsed['itens'][idx].get('ncm'),
                    cfop=parsed['itens'][idx].get('cfop'),
                    ativo=True
                )
                db.session.add(product)
                novos += 1
            
            db.session.flush()

        # 2. Registra o XML e lança no Financeiro (Contas a Pagar)
        if raw_xml_b64:
            raw_xml = base64.b64decode(raw_xml_b64.encode('ascii'))
            parsed = parse_nfe_xml(raw_xml)
            
            vencimento_padrao = request.form.get('vencimento_padrao')
            
            existing_xml = XmlInvoiceImport.query.filter_by(chave_acesso=parsed['chave_acesso']).first()
            if not existing_xml:
                supplier = Client.query.filter_by(cpf_cnpj=parsed.get('emitente_cnpj')).first()
                if not supplier:
                    supplier = Client(nome=parsed.get('emitente_nome') or 'Fornecedor XML', cpf_cnpj=parsed.get('emitente_cnpj'))
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
                        data_venc = vencimento_padrao if vencimento_padrao else (fatura['vencimento'] or parsed.get('issued_at'))
                        create_financial_entries(
                            entry_type='PAGAR',
                            descricao=f"NF-e {parsed.get('numero')} - {parsed.get('emitente_nome')} (Dup. {fatura['numero']})",
                            categoria='NF-e XML',
                            valor_total=parse_decimal(fatura['valor']),
                            vencimento=data_venc,
                            status='PENDENTE',
                            reference_type='XML_NFE',
                            reference_id=xml_import.id,
                            installment_count=1
                        )
                else:
                    data_venc = vencimento_padrao if vencimento_padrao else parsed.get('issued_at')
                    create_financial_entries(
                        entry_type='PAGAR',
                        descricao=f"NF-e {parsed.get('numero')} - {parsed.get('emitente_nome')}",
                        categoria='NF-e XML',
                        valor_total=parse_decimal(parsed.get('total_nota')),
                        vencimento=data_venc,
                        status='PENDENTE',
                        reference_type='XML_NFE',
                        reference_id=xml_import.id,
                        installment_count=1
                    )

        db.session.commit()
        flash(f'Importação concluída: {novos} peças novas e {atualizados} atualizadas. NF-e enviada ao Financeiro!', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Falha ao salvar as peças e financeiro: {exc}', 'error')

    return redirect(url_for('web.products_index'))


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
def budgets_index():
    page = paginate_query(Budget.query.order_by(Budget.id.desc()))
    return render_template('orcamentos/index.html', budgets=page['items'], pagination=page)


@web_bp.route('/orcamentos/novo', methods=['GET', 'POST'])
@login_required
def budgets_new():
    clients = Client.query.order_by(Client.nome).all()
    if request.method == 'POST':
        budget = Budget(numero=next_number(Budget, get_system_settings().budget_prefix or 'ORC'))
        _fill_budget_from_form(budget)
        db.session.add(budget)
        db.session.commit()
        flash('Orçamento criado.', 'success')
        return redirect(url_for('web.budgets_show', budget_id=budget.id))
    return render_template('orcamentos/form.html', budget=None, clients=clients, statuses=BUDGET_STATUSES, budget_default_date=budget_default_date())


@web_bp.route('/orcamentos/<int:budget_id>/editar', methods=['GET', 'POST'])
@login_required
def budgets_edit(budget_id: int):
    budget = db.session.get(Budget, budget_id)
    if not budget:
        return redirect(url_for('web.budgets_index'))
    clients = Client.query.order_by(Client.nome).all()
    if request.method == 'POST':
        _fill_budget_from_form(budget)
        if 'status' in request.form:
            budget.status = request.form.get('status') or budget.status
        recalculate_budget_totals(budget)
        db.session.commit()
        flash('Orçamento atualizado.', 'success')
        return redirect(url_for('web.budgets_show', budget_id=budget.id))
    return render_template('orcamentos/form.html', budget=budget, clients=clients, statuses=BUDGET_STATUSES)


@web_bp.get('/orcamentos/<int:budget_id>')
@login_required
def budgets_show(budget_id: int):
    budget = db.session.get(Budget, budget_id)
    if not budget:
        return redirect(url_for('web.budgets_index'))
    services = Service.query.filter_by(ativo=True).order_by(Service.nome).all()
    products = Product.query.filter_by(ativo=True).order_by(Product.nome).all()
    return render_template('orcamentos/show.html', budget=budget, services=services, products=products)


@web_bp.post('/orcamentos/<int:budget_id>/itens')
@login_required
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
        
    orders_page = paginate_query(query.order_by(WorkOrder.id.desc()))
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
    
    return render_template('os/index.html', orders=orders, pagination=orders_page, statuses=WORK_ORDER_STATUSES, receivables_by_order=receivables_by_order, payment_methods=payment_methods, bank_accounts=bank_accounts)

@web_bp.post('/os/<int:work_order_id>/copiar')
@login_required
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
        status_history=order.status_history,
    )



@web_bp.get('/os/<int:work_order_id>/pdf')
@login_required
def work_orders_pdf(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    is_receipt = request.args.get('recibo') == '1'
    pdf_bytes = generate_work_order_pdf(
        order,
        [item for item in order.items if item.item_type == 'SERVICO'],
        [item for item in order.items if item.item_type == 'PECA'],
        company_name=get_system_settings().company_name or 'ERP Auto Center',
        document_title='RECIBO COMPLETO DA O.S.' if is_receipt else 'ORDEM DE SERVIÇO',
    )
    return send_file(
        __import__('io').BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=request.args.get('download') != '0',
        download_name=f'{"recibo" if is_receipt else "os"}-{order.numero}.pdf',
    )


@web_bp.post('/os/<int:work_order_id>/itens')
@login_required
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
        flash('Status atualizado.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for('web.work_orders_show', work_order_id=order.id))


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
    entries = ensure_work_order_receivables(order)
    db.session.commit()
    if len(entries) > 1:
        flash(f'{len(entries)} parcelas lançadas em contas a receber.', 'success')
    else:
        flash('Conta a receber lançada com sucesso.', 'success')
    return redirect(url_for('web.finance_index'))


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
@admin_required
def finance_index():
    termo_pesquisa = request.args.get('q', '').strip()
    
    # ⚡ OTIMIZAÇÃO: Traz a Fatura, Conta Bancária e Forma de Pagamento em 1 viagem
    query = FinancialEntry.query.options(
        joinedload(FinancialEntry.payment_method),
        joinedload(FinancialEntry.bank_account)
    )
    
    if termo_pesquisa:
        filtro = f"%{termo_pesquisa}%"
        query = query.filter(
            db.or_(
                FinancialEntry.descricao.ilike(filtro),
                FinancialEntry.categoria.ilike(filtro)
            )
        )
        
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    sort_order = request.args.get('sort_order', 'desc')
    
    from datetime import datetime
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            query = query.filter(FinancialEntry.vencimento >= start_date)
        except ValueError:
            pass
            
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            query = query.filter(FinancialEntry.vencimento <= end_date)
        except ValueError:
            pass
            
    if sort_order == 'asc':
        query = query.order_by(FinancialEntry.vencimento.asc(), FinancialEntry.id.asc())
    else:
        query = query.order_by(FinancialEntry.vencimento.desc(), FinancialEntry.id.desc())
        
    entries_page = paginate_query(query)
    entries = entries_page['items']
    
    work_order_ids = {entry.reference_id for entry in entries if entry.reference_type == 'OS' and entry.reference_id}
    work_orders_by_id = {order.id: order for order in WorkOrder.query.filter(WorkOrder.id.in_(work_order_ids)).all()} if work_order_ids else {}
    
    xml_import_ids = {entry.reference_id for entry in entries if entry.reference_type == 'XML_NFE' and entry.reference_id}
    xml_imports_by_id = {xml_import.id: xml_import for xml_import in XmlInvoiceImport.query.filter(XmlInvoiceImport.id.in_(xml_import_ids)).all()} if xml_import_ids else {}
    
    payment_methods = PaymentMethod.query.filter_by(ativo=True).order_by(PaymentMethod.nome).all()
    bank_accounts = BankAccount.query.filter_by(ativo=True).order_by(BankAccount.nome).all()
    
    total_receber = db.session.query(db.func.coalesce(db.func.sum(FinancialEntry.valor), 0)).filter(FinancialEntry.entry_type == 'RECEBER', FinancialEntry.status == 'PENDENTE').scalar() or 0
    total_pagar = db.session.query(db.func.coalesce(db.func.sum(FinancialEntry.valor), 0)).filter(FinancialEntry.entry_type == 'PAGAR', FinancialEntry.status == 'PENDENTE').scalar() or 0
    
    entry_groups = _group_financial_entries(entries)
    
    # ⚡ OTIMIZAÇÃO: Nas abas de NFE e NFSE, já atrela a OS de origem junto
    nfe_docs = FiscalDocument.query.options(joinedload(FiscalDocument.work_order)).filter_by(document_type='NFE').order_by(FiscalDocument.id.desc()).limit(100).all()
    nfse_docs = FiscalDocument.query.options(joinedload(FiscalDocument.work_order)).filter_by(document_type='NFSE').order_by(FiscalDocument.id.desc()).limit(100).all()
    
    return render_template(
        'financeiro/index.html', 
        entries=entries, 
        entry_groups=entry_groups, 
        payment_methods=payment_methods, 
        bank_accounts=bank_accounts, 
        cash=dashboard_data('ADMINISTRADOR')['caixa_diario'], 
        total_receber=total_receber, 
        total_pagar=total_pagar,
        pagination=entries_page,
        work_orders_by_id=work_orders_by_id,
        xml_imports_by_id=xml_imports_by_id,
        nfe_docs=nfe_docs,
        nfse_docs=nfse_docs,
    )

@web_bp.route('/financeiro/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def finance_new():
    if request.method == 'GET':
        payment_methods = PaymentMethod.query.filter_by(ativo=True).order_by(PaymentMethod.nome).all()
        bank_accounts = BankAccount.query.filter_by(ativo=True).order_by(BankAccount.nome).all()
        return render_template('financeiro/form.html', payment_methods=payment_methods, bank_accounts=bank_accounts)

    entry_type = request.form.get('entry_type') or 'RECEBER'
    payment_mode = request.form.get('payment_mode') or 'UNICO'
    installment_count = int(request.form.get('installment_count') or 1)
    installment_value = parse_decimal(request.form.get('installment_value'))
    total_value = parse_decimal(request.form.get('valor'))
    
    if entry_type == 'PAGAR' and payment_mode == 'PARCELADO':
        installment_count = max(installment_count, 1)
        total_value = installment_value * installment_count
    else:
        installment_count = 1
        
    entries = create_financial_entries(
        entry_type=entry_type,
        descricao=request.form.get('descricao', '').strip(),
        categoria=request.form.get('categoria') or None,
        valor_total=total_value,
        vencimento=request.form.get('vencimento'),
        status=request.form.get('status') or 'PENDENTE',
        payment_method_id=int(request.form.get('payment_method_id')) if request.form.get('payment_method_id') else None,
        bank_account_id=int(request.form.get('bank_account_id')) if request.form.get('bank_account_id') else None,
        reference_type=request.form.get('reference_type') or None,
        reference_id=int(request.form.get('reference_id')) if request.form.get('reference_id') else None,
        installment_count=installment_count,
        payment_receipt_at=request.form.get('payment_receipt_at'),
    )
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
    settle_financial_entry(entry, payment_method_id=int(request.form.get('payment_method_id')) if request.form.get('payment_method_id') else None, payment_receipt_at=request.form.get('payment_receipt_at'), bank_account_id=int(request.form.get('bank_account_id')) if request.form.get('bank_account_id') else None)
    db.session.commit()
    flash('Lançamento liquidado.', 'success')
    return redirect(url_for('web.finance_index'))




@web_bp.post('/financeiro/importar-xml/preview')
@login_required
@admin_required
def finance_import_xml_preview():
    upload = request.files.get('xml_file')
    if not upload or not upload.filename:
        flash('Selecione um arquivo XML.', 'error')
        return redirect(url_for('web.finance_index'))
    try:
        raw_xml = upload.read()
        parsed = parse_nfe_xml(raw_xml)
        return render_template(
            'financeiro/xml_preview.html',
            parsed=parsed,
            raw_xml_b64=base64.b64encode(raw_xml).decode('ascii'),
            existing=XmlInvoiceImport.query.filter_by(chave_acesso=parsed['chave_acesso']).first(),
        )
    except Exception as exc:
        flash(f'Falha ao ler XML: {exc}', 'error')
        return redirect(url_for('web.finance_index'))


@web_bp.post('/financeiro/importar-xml/confirmar')
@login_required
@admin_required
def finance_import_xml_confirm():
    raw_xml_b64 = request.form.get('raw_xml_b64') or ''
    if not raw_xml_b64:
        flash('Prévia do XML expirada. Envie o arquivo novamente.', 'error')
        return redirect(url_for('web.finance_index'))
    try:
        raw_xml = base64.b64decode(raw_xml_b64.encode('ascii'))
        parsed = parse_nfe_xml(raw_xml)
        existing = XmlInvoiceImport.query.filter_by(chave_acesso=parsed['chave_acesso']).first()
        if existing:
            flash('Este XML já foi importado.', 'warning')
            return redirect(url_for('web.finance_index'))

        supplier = Client.query.filter_by(cpf_cnpj=parsed.get('emitente_cnpj')).first()
        if not supplier:
            supplier = Client(nome=parsed.get('emitente_nome') or 'Fornecedor XML', cpf_cnpj=parsed.get('emitente_cnpj'))
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
            raw_xml=raw_xml.decode('utf-8', errors='ignore'),
        )
        xml_import.set_items(parsed.get('itens') or [])
        db.session.add(xml_import)
        db.session.flush()

        create_financial_entries(
            entry_type='PAGAR',
            descricao=f"NF-e {parsed.get('numero')} - {parsed.get('emitente_nome')}",
            categoria='NF-e XML',
            valor_total=parse_decimal(parsed.get('total_nota')),
            vencimento=parsed.get('issued_at'),
            status='PENDENTE',
            reference_type='XML_NFE',
            reference_id=xml_import.id,
            installment_count=1,
        )
        db.session.commit()
        flash('XML importado e conta a pagar gerada.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Falha ao importar XML: {exc}', 'error')
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
    linked_documents = FiscalDocument.query.filter_by(work_order_id=None, document_type='NFE').order_by(FiscalDocument.id.desc()).limit(PAGE_SIZE).all()
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
    return redirect(url_for('web.settings_index') + '#fiscal-documentos')


@web_bp.post('/fiscal/configuracoes')
@login_required
@admin_required
def fiscal_save_config():
    save_fiscal_config_from_form(request.form)
    db.session.commit()
    flash('Configurações fiscais salvas.', 'success')
    return redirect(url_for('web.settings_index') + '#fiscal')


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
            return render_template('fiscal/parts_invoice.html', config=config, form=form, xml_imports=xml_imports, products=products, selected_product=selected_product, source_import=source_import, source_details=source_details, supplier_client=supplier_client, missing_fields=missing_fields, invoice_items=_parts_invoice_form_items(form, source_import, selected_product))
            
        if not any((value or '').strip() for value in form.getlist('item_descricao')):
            flash('Informe pelo menos um produto.', 'error')
            return render_template('fiscal/parts_invoice.html', config=config, form=form, xml_imports=xml_imports, products=products, selected_product=selected_product, source_import=source_import, source_details=source_details, supplier_client=supplier_client, missing_fields=missing_fields, invoice_items=_parts_invoice_form_items(form, source_import, selected_product))
            
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
                flash(f'Emissão recusada pela Focus NFe: {document.error_message or "verifique o documento fiscal"}', 'error')
            else:
                flash('NF-e de peças enviada para a Focus NFe.' if form.get('emitir') else 'NF-e de peças salva como preparada.', 'success')
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
            
    return render_template('fiscal/parts_invoice.html', config=config, form=request.form, xml_imports=xml_imports, products=products, selected_product=selected_product, source_import=source_import, source_details=source_details, supplier_client=supplier_client, missing_fields=missing_fields, invoice_items=_parts_invoice_form_items(request.form, source_import, selected_product))

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
    return render_template(template, order=order, payload=payload, config=config, document=document)


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
            flash(f'Emissão recusada pela Focus NFe: {document.error_message or "verifique o documento fiscal"}', 'error')
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
    if not document or not config or config.provider_name != 'FOCUSNFE':
        flash('Documento ou integração Focus NFe não disponível.', 'error')
        return redirect(url_for('web.fiscal_index'))
    try:
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
    try:
        issue_with_external_api(document, config)
        db.session.commit()
        if document.status == 'ERRO':
            flash(f'Emissão recusada pela Focus NFe: {document.error_message or "verifique o documento fiscal"}', 'error')
        else:
            flash('Nota enviada para a Focus NFe.', 'success')
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
    if not config or config.provider_name != 'FOCUSNFE':
        flash('Integração Focus NFe não disponível.', 'error')
        if origem == 'financeiro':
            return redirect(url_for('web.finance_index'))
        return redirect(url_for('web.settings_index') + '#fiscal-documentos')
        
    try:
        justificativa = request.form.get('justificativa') or 'Cancelamento solicitado pelo usuario'
        if document.document_type == 'NFSE':
            from .fiscal import cancel_focus_nfse
            cancel_focus_nfse(document, config, justificativa)
        else:
            from .fiscal import cancel_focus_nfe
            cancel_focus_nfe(document, config, justificativa)
        db.session.commit()
        flash('Nota cancelada com sucesso.', 'success')
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

@web_bp.post('/os/<int:work_order_id>/excluir')
@login_required
@admin_required
def work_orders_delete(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    
    entradas_fin = FinancialEntry.query.filter_by(reference_type='OS', reference_id=order.id).all()
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
        # Estorna o saldo da conta bancária
        if entry.bank_account_id:
            account = db.session.get(BankAccount, entry.bank_account_id)
            if account:
                value = parse_decimal(entry.valor)
                if entry.entry_type == 'RECEBER':
                    account.saldo_atual = parse_decimal(account.saldo_atual) - value
                else:
                    account.saldo_atual = parse_decimal(account.saldo_atual) + value
                    
        # Reverte o lançamento para pendente
        entry.status = 'PENDENTE'
        entry.payment_receipt_at = None
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
            val = parse_decimal(entry.valor)
            if entry.entry_type == 'RECEBER':
                account.saldo_atual = parse_decimal(account.saldo_atual) - val
            else:
                account.saldo_atual = parse_decimal(account.saldo_atual) + val
                
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
    clients = Client.query.order_by(Client.nome).all()
    employees = Employee.query.filter_by(ativo=True).order_by(Employee.nome).all()
    payment_methods = PaymentMethod.query.filter_by(ativo=True).order_by(PaymentMethod.nome).all()
    services = Service.query.filter_by(ativo=True).order_by(Service.nome).all()
    products = Product.query.filter_by(ativo=True).order_by(Product.nome).all()
    return render_template(
        'os/form.html',
        order=order,
        clients=clients,
        employees=employees,
        payment_methods=payment_methods,
        statuses=WORK_ORDER_STATUSES,
        service_rows=_item_rows_for_template(order, 'servico', 'SERVICO'),
        product_rows=_item_rows_for_template(order, 'peca', 'PECA'),
        service_price_map={service.nome.lower(): float(parse_decimal(service.preco_base)) for service in services},
        product_price_map={product.nome.lower(): float(parse_decimal(product.preco_venda)) for product in products},
        services=services,
        products=products,
    )


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
    order.emitir_nota = True

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
    status_filter = request.args.getlist('status')
    if not status_filter:
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
            if show_items == 'pecas' and item.item_type != 'peca':
                continue
            if show_items == 'servicos' and item.item_type != 'servico':
                continue
            filtered_items.append(item)
            
        if show_items != 'both' and not filtered_items and len(order.items) > 0:
            continue
            
        order.filtered_items = filtered_items
        
        o_servicos = sum([i.total for i in filtered_items if i.item_type == 'servico'])
        o_pecas = sum([i.total for i in filtered_items if i.item_type == 'peca'])
        o_desconto = sum([i.desconto for i in filtered_items])
        o_total = o_servicos + o_pecas
        
        order.calc_servicos = o_servicos
        order.calc_pecas = o_pecas
        order.calc_desconto = o_desconto
        order.calc_total = o_total
        
        total_servicos += o_servicos
        total_pecas += o_pecas
        total_desconto += o_desconto
        total_geral += o_total
        
        orders.append(order)
        
    clients = Client.query.order_by(Client.nome).all()
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
                           clients=clients,
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
        return redirect(url_for('web.reports_index'))
        
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
        return redirect(url_for('web.reports_index'))
        
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


