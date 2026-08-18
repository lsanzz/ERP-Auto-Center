from __future__ import annotations

from collections import OrderedDict
import base64
import io
import json
import re
from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from decimal import Decimal

from .auth import admin_required, current_user, login_required, login_user, logout_user
from .cnpj import is_cnpj, is_cpf, lookup_cnpj, lookup_cpf
from .models import BankAccount, Budget, Client, Employee, FinancialEntry, FiscalApiConfig, FiscalDocument, PaymentMethod, Product, Service, User, WorkOrder, XmlInvoiceImport, db
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
)
from .pdfs import generate_work_order_pdf
from .utils import parse_date, parse_decimal, format_currency
from .xml_import import parse_nfe_xml
from .fiscal import (
    build_work_order_invoice_payload,
    create_or_update_fiscal_document,
    decode_payload,
    get_fiscal_config,
    import_external_payload,
    issue_with_external_api,
    preview_external_import,
    save_fiscal_config_from_form,
)


web_bp = Blueprint('web', __name__)


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

@web_bp.get('/clientes')
@login_required
def clients_index():
    clients = Client.query.order_by(Client.nome).all()
    return render_template('clientes/index.html', clients=clients)


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


@web_bp.get('/produtos')
@login_required
def products_index():
    products = Product.query.order_by(Product.nome).all()
    return render_template('produtos/index.html', products=products)


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
                atualizados += 1
            else:
                product = Product(
                    codigo=codigo,
                    nome=nomes[idx],
                    unidade=unidades[idx],
                    custo=custo_val,
                    preco_venda=venda_val,
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
    services = Service.query.order_by(Service.nome).all()
    return render_template('servicos/index.html', services=services)


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
    budgets = Budget.query.order_by(Budget.id.desc()).all()
    return render_template('orcamentos/index.html', budgets=budgets)


@web_bp.route('/orcamentos/novo', methods=['GET', 'POST'])
@login_required
def budgets_new():
    clients = Client.query.order_by(Client.nome).all()
    if request.method == 'POST':
        budget = Budget(numero=next_number(Budget, 'ORC'))
        _fill_budget_from_form(budget)
        db.session.add(budget)
        db.session.commit()
        flash('Orçamento criado.', 'success')
        return redirect(url_for('web.budgets_show', budget_id=budget.id))
    return render_template('orcamentos/form.html', budget=None, clients=clients, statuses=BUDGET_STATUSES)


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


@web_bp.get('/os')
@login_required
def work_orders_index():
    orders = WorkOrder.query.order_by(WorkOrder.id.desc()).all()
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
    return render_template('os/index.html', orders=orders, receivables_by_order=receivables_by_order, payment_methods=payment_methods, bank_accounts=bank_accounts)


@web_bp.route('/os/nova', methods=['GET', 'POST'])
@login_required
def work_orders_new():
    order = None
    if request.method == 'POST':
        order = WorkOrder(numero=next_number(WorkOrder, 'OS'), status=request.form.get('status') or 'ABERTA')
        try:
            _fill_work_order_from_form(order)
            db.session.add(order)
            db.session.flush()
            _sync_work_order_items_from_form(order)
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
            _fill_work_order_from_form(order)
            _sync_work_order_items_from_form(order)
            if 'status' in request.form and request.form.get('status') in WORK_ORDER_STATUSES:
                order.status = request.form.get('status')
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
    return render_template(
        'os/show.html',
        order=order,
        statuses=WORK_ORDER_STATUSES,
        service_items=[item for item in order.items if item.item_type == 'SERVICO'],
        part_items=[item for item in order.items if item.item_type == 'PECA'],
        installment_values=installment_values,
    )



@web_bp.get('/os/<int:work_order_id>/pdf')
@login_required
def work_orders_pdf(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    pdf_bytes = generate_work_order_pdf(
        order,
        [item for item in order.items if item.item_type == 'SERVICO'],
        [item for item in order.items if item.item_type == 'PECA'],
    )
    return send_file(
        __import__('io').BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'os-{order.numero}.pdf',
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
        change_work_order_status(order, request.form.get('status', ''))
        db.session.commit()
        flash('Status atualizado.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for('web.work_orders_show', work_order_id=order.id))


@web_bp.post('/os/<int:work_order_id>/finalizar')
@login_required
def work_orders_finish(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    order.status = 'FINALIZADA'
    if not order.data_saida:
        order.data_saida = parse_date(request.form.get('data_saida')) or __import__('datetime').date.today()
    recalculate_work_order_totals(order)
    db.session.commit()
    flash('O.S. finalizada. Use o menu de ações para lançar o contas a receber.', 'success')
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


@web_bp.get('/financeiro')
@login_required
@admin_required
def finance_index():
    entries = FinancialEntry.query.order_by(FinancialEntry.vencimento.desc(), FinancialEntry.id.desc()).all()
    # Necessários para o form inline de liquidar
    payment_methods = PaymentMethod.query.filter_by(ativo=True).order_by(PaymentMethod.nome).all()
    bank_accounts = BankAccount.query.filter_by(ativo=True).order_by(BankAccount.nome).all()
    
    total_receber = sum(parse_decimal(entry.valor) for entry in entries if entry.entry_type == 'RECEBER' and entry.status == 'PENDENTE')
    total_pagar = sum(parse_decimal(entry.valor) for entry in entries if entry.entry_type == 'PAGAR' and entry.status == 'PENDENTE')
    entry_groups = _group_financial_entries(entries)
    
    return render_template(
        'financeiro/index.html', 
        entries=entries, 
        entry_groups=entry_groups, 
        payment_methods=payment_methods, 
        bank_accounts=bank_accounts, 
        cash=dashboard_data('ADMINISTRADOR')['caixa_diario'], 
        total_receber=total_receber, 
        total_pagar=total_pagar
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
    xml_imports = XmlInvoiceImport.query.order_by(XmlInvoiceImport.id.desc()).limit(20).all()
    return render_template('financeiro/importacoes.html', xml_imports=xml_imports)


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
    parsed = xml_import.to_dict()
    parsed['itens'] = xml_import.get_items()
    return render_template('financeiro/xml_preview_saved.html', xml_import=xml_import, parsed=parsed)


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
    config = get_fiscal_config()
    documents = FiscalDocument.query.order_by(FiscalDocument.id.desc()).limit(20).all()
    work_orders = WorkOrder.query.order_by(WorkOrder.id.desc()).limit(20).all()
    return render_template('fiscal/index.html', config=config, documents=documents, work_orders=work_orders)


@web_bp.post('/fiscal/configuracoes')
@login_required
@admin_required
def fiscal_save_config():
    save_fiscal_config_from_form(request.form)
    db.session.commit()
    flash('Configurações fiscais salvas.', 'success')
    return redirect(url_for('web.fiscal_index'))


@web_bp.get('/os/<int:work_order_id>/nota/preview')
@login_required
@admin_required
def work_order_invoice_preview(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    config = get_fiscal_config()
    payload = build_work_order_invoice_payload(order, config)
    document = FiscalDocument.query.filter_by(work_order_id=order.id).order_by(FiscalDocument.id.desc()).first()
    return render_template('fiscal/issue_preview.html', order=order, payload=payload, config=config, document=document)


@web_bp.post('/os/<int:work_order_id>/nota/preparar')
@login_required
@admin_required
def work_order_invoice_prepare(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    config = get_fiscal_config()
    document = create_or_update_fiscal_document(order, config)
    db.session.commit()
    flash('Prévia fiscal gerada. Revise os dados antes de emitir.', 'success')
    return redirect(url_for('web.work_order_invoice_preview', work_order_id=order.id))


@web_bp.post('/os/<int:work_order_id>/nota/emitir')
@login_required
@admin_required
def work_order_invoice_issue(work_order_id: int):
    order = db.session.get(WorkOrder, work_order_id)
    if not order:
        return redirect(url_for('web.work_orders_index'))
    config = get_fiscal_config()
    if not config:
        flash('Configure a integração fiscal antes de emitir.', 'error')
        return redirect(url_for('web.work_order_invoice_preview', work_order_id=work_order_id))
    try:
        document = create_or_update_fiscal_document(order, config)
        issue_with_external_api(document, config)
        db.session.commit()
        flash('Documento fiscal enviado para a API configurada.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Falha ao emitir nota: {exc}', 'error')
    return redirect(url_for('web.work_order_invoice_preview', work_order_id=work_order_id))


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

@web_bp.get('/formas-pagamento')
@login_required
@admin_required
def payment_methods_index():
    methods = PaymentMethod.query.order_by(PaymentMethod.nome).all()
    return render_template('formas_pagamento/index.html', methods=methods)


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
    employees = Employee.query.order_by(Employee.nome).all()
    return render_template('funcionarios/index.html', employees=employees)


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

    return [{'descricao': '', 'quantidade': '1.00', 'valor_unitario': '0.00', 'total': '0.00'}]


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
    product.custo = parse_decimal(request.form.get('custo'))
    product.preco_venda = parse_decimal(request.form.get('preco_venda'))
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
    budget.validade = parse_date(request.form.get('validade'))
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
