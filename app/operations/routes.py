from __future__ import annotations

from pathlib import Path
from datetime import date, datetime, timedelta
from PIL import Image, ImageOps, UnidentifiedImageError
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from ..auth import admin_required, current_user, login_required, permission_required
from ..models import Budget, Product, Supplier, WorkOrder, db
from ..utils import format_currency, parse_date
from .models import AuditEvent, InspectionPhoto, InventoryMovement, StockReservation
from .services import (
    INSPECTION_CONDITIONS,
    adjust_stock,
    receive_stock,
    create_budget_approval,
    ensure_inspection,
    find_budget_approval,
    record_audit,
    release_order_reservations,
    reserve_order_parts,
    respond_to_budget_approval,
    update_inspection,
)


operations_bp = Blueprint('operations', __name__, url_prefix='/operacao')
ALLOWED_IMAGE_TYPES = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}
IMAGE_FORMATS = {'JPEG': ('image/jpeg', '.jpg'), 'PNG': ('image/png', '.png'), 'WEBP': ('image/webp', '.webp')}
Image.MAX_IMAGE_PIXELS = 24_000_000


def _uploads_path() -> Path:
    path = Path(current_app.instance_path) / 'uploads' / 'inspections'
    path.mkdir(parents=True, exist_ok=True)
    return path


@operations_bp.route('/os/<int:work_order_id>/inspecao', methods=['GET', 'POST'])
@login_required
@permission_required('inspections.manage')
def inspection(work_order_id):
    order = db.get_or_404(WorkOrder, work_order_id)
    inspection_model = ensure_inspection(order)
    if request.method == 'POST':
        try:
            update_inspection(inspection_model, request.form, current_user().id)
            record_audit('ATUALIZAR', 'INSPECAO', inspection_model.id, current_user().id,
                         {'status': inspection_model.status}, request.remote_addr)
            db.session.commit()
            flash('Inspecao salva.', 'success')
            return redirect(url_for('operations.inspection', work_order_id=order.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
    return render_template('operacao/inspection.html', order=order, inspection=inspection_model,
                           conditions=INSPECTION_CONDITIONS)


@operations_bp.post('/os/<int:work_order_id>/inspecao/fotos')
@login_required
@permission_required('inspections.manage')
def inspection_photo(work_order_id):
    order = db.get_or_404(WorkOrder, work_order_id)
    inspection_model = ensure_inspection(order)
    upload = request.files.get('photo')
    if not upload or not upload.filename:
        flash('Selecione uma foto.', 'error')
        return redirect(url_for('operations.inspection', work_order_id=order.id))
    try:
        image = Image.open(upload.stream)
        image.verify()
        upload.stream.seek(0)
        image = Image.open(upload.stream)
        content_type, suffix = IMAGE_FORMATS[image.format]
        image = ImageOps.exif_transpose(image)
        image.thumbnail((4096, 4096))
    except (UnidentifiedImageError, KeyError, OSError, Image.DecompressionBombError):
        flash('Formato invalido. Envie JPG, PNG ou WEBP.', 'error')
        return redirect(url_for('operations.inspection', work_order_id=order.id))
    storage_name = f'{uuid4().hex}{suffix}'
    save_format = 'JPEG' if suffix == '.jpg' else suffix[1:].upper()
    if save_format == 'JPEG' and image.mode not in ('RGB', 'L'):
        image = image.convert('RGB')
    image.save(_uploads_path() / storage_name, format=save_format, optimize=True, quality=88)
    photo = InspectionPhoto(
        inspection=inspection_model, storage_name=storage_name,
        original_name=secure_filename(upload.filename)[:255] or f'foto{suffix}',
        content_type=content_type, caption=(request.form.get('caption') or '').strip() or None,
    )
    db.session.add(photo)
    record_audit('ANEXAR_FOTO', 'INSPECAO', inspection_model.id, current_user().id,
                 {'arquivo': photo.original_name}, request.remote_addr)
    db.session.commit()
    flash('Foto adicionada a inspecao.', 'success')
    return redirect(url_for('operations.inspection', work_order_id=order.id))


@operations_bp.get('/inspecao/fotos/<int:photo_id>')
@login_required
@permission_required('work_orders.view')
def inspection_photo_file(photo_id):
    photo = db.get_or_404(InspectionPhoto, photo_id)
    return send_from_directory(_uploads_path(), photo.storage_name, mimetype=photo.content_type)


@operations_bp.post('/orcamentos/<int:budget_id>/solicitar-aprovacao')
@login_required
@permission_required('approvals.manage')
def issue_budget_approval(budget_id):
    budget = db.get_or_404(Budget, budget_id)
    approval, raw_token = create_budget_approval(budget, current_user().id)
    record_audit('CRIAR_LINK', 'ORCAMENTO', budget.id, current_user().id, ip=request.remote_addr)
    db.session.commit()
    approval_url = url_for('operations.public_budget_approval', token=raw_token, _external=True)
    return render_template('operacao/approval_link.html', budget=budget, approval=approval, approval_url=approval_url)


@operations_bp.route('/aprovar/<token>', methods=['GET', 'POST'])
def public_budget_approval(token):
    approval = find_budget_approval(token)
    if not approval:
        abort(404)
    error = None
    if request.method == 'POST':
        try:
            respond_to_budget_approval(
                approval, request.form.get('decision'), request.form,
                request.remote_addr, request.user_agent.string,
            )
            record_audit('RESPONDER', 'ORCAMENTO', approval.budget_id, None,
                         {'decisao': approval.status, 'nome': approval.response_name}, request.remote_addr)
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            error = str(exc)
            if approval.status == 'PENDENTE' and approval.expires_at < datetime.now():
                approval.status = 'EXPIRADO'  # o rollback desfaria a marcação feita na validação
                db.session.commit()
    return render_template('operacao/public_approval.html', approval=approval, budget=approval.budget, error=error)


@operations_bp.get('/estoque')
@login_required
@permission_required('inventory.view')
def inventory():
    products = Product.query.filter_by(ativo=True).order_by(Product.nome).all()
    reserved = dict(
        db.session.query(StockReservation.product_id, db.func.sum(StockReservation.quantity))
        .filter(StockReservation.status == 'ATIVA').group_by(StockReservation.product_id).all()
    )
    movements = InventoryMovement.query.order_by(InventoryMovement.id.desc()).limit(100).all()
    usage = dict(db.session.query(InventoryMovement.product_id, db.func.sum(-InventoryMovement.quantity)).filter(
        InventoryMovement.quantity < 0, InventoryMovement.created_at >= datetime.now() - timedelta(days=90),
        InventoryMovement.movement_type != 'ESTORNO').group_by(InventoryMovement.product_id).all())
    values = sorted(((product.id, float(product.estoque_atual * product.custo)) for product in products), key=lambda row: row[1], reverse=True)
    total_value = sum(value for _, value in values) or 1
    cumulative = 0; abc = {}
    for product_id, value in values:
        cumulative += value
        share = cumulative / total_value
        abc[product_id] = 'A' if share <= .80 else ('B' if share <= .95 else 'C')
    metrics = {}
    for product in products:
        consumed = float(usage.get(product.id, 0) or 0)
        metrics[product.id] = {'abc': abc.get(product.id, 'C'), 'coverage': round(float(product.estoque_atual) / (consumed / 90), 1) if consumed > 0 else None}
    reversed_ids = {row.reversal_of_id for row in movements if row.reversal_of_id}
    from ..web import finance_form_context, paginate_query
    search = request.args.get('q', '').strip()
    listed = Product.query.filter_by(ativo=True)
    if search:
        listed = listed.filter(db.or_(Product.nome.ilike(f'%{search}%'), Product.codigo.ilike(f'%{search}%')))
    page = paginate_query(listed.order_by(Product.nome))
    return render_template('operacao/inventory.html', products=page['items'], pagination=page, search=search,
                           all_products=products, suppliers=Supplier.query.filter_by(ativo=True).order_by(Supplier.nome).all(),
                           reserved=reserved, movements=movements, metrics=metrics, reversed_ids=reversed_ids,
                           today=date.today(), **finance_form_context())


@operations_bp.post('/estoque/entrada')
@login_required
@permission_required('inventory.move')
def inventory_receive():
    from ..services import create_financial_entries
    try:
        supplier = db.session.get(Supplier, request.form.get('supplier_id', type=int))
        if not supplier:
            raise ValueError('Selecione o fornecedor.')
        codes = {product.codigo: product for product in Product.query.filter(Product.codigo.in_(
            [text.split(' · ')[0].strip() for text in request.form.getlist('produto') if text.strip()]))}
        items = []
        for text, quantity, cost in zip(request.form.getlist('produto'), request.form.getlist('quantidade'),
                                        request.form.getlist('custo')):
            if not text.strip():
                continue
            product = codes.get(text.split(' · ')[0].strip())
            if not product:
                raise ValueError(f'Peça não encontrada: {text}. Cadastre em Peças e produtos antes.')
            items.append((product, quantity, cost))
        received = parse_date(request.form.get('data_entrada')) or date.today()
        entry = receive_stock(supplier, items, request.form.get('numero_nota'), received, current_user().id)
        if request.form.get('gerar_conta'):
            nota = f' · NF {entry.numero_nota}' if entry.numero_nota else ''
            create_financial_entries(
                entry_type='PAGAR', descricao=f'Compra de peças · {supplier.nome}{nota}'[:255], categoria='Compra de peças',
                valor_total=entry.valor_total, vencimento=request.form.get('vencimento') or received,
                status='PAGO' if request.form.get('status') == 'LIQUIDADO' else 'PENDENTE',
                payment_method_id=request.form.get('payment_method_id', type=int),
                bank_account_id=request.form.get('bank_account_id', type=int),
                reference_type='ENTRADA_ESTOQUE', reference_id=entry.id,
                installment_count=max(request.form.get('installment_count', 1, type=int) or 1, 1),
                payment_receipt_at=received,
            )
        record_audit('ENTRADA_ESTOQUE', 'STOCK_ENTRY', entry.id, current_user().id,
                     {'itens': len(items), 'total': str(entry.valor_total)}, request.remote_addr)
        db.session.commit()
        flash(f'Entrada lançada: {len(items)} peça(s), total {format_currency(entry.valor_total)}.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for('operations.inventory'))


@operations_bp.post('/estoque/produtos/<int:product_id>/ajustar')
@login_required
@permission_required('inventory.move')
def inventory_adjust(product_id):
    product = db.get_or_404(Product, product_id)
    try:
        adjust_stock(product, request.form.get('balance'), request.form.get('reason'), current_user().id)
        record_audit('AJUSTAR_ESTOQUE', 'PRODUTO', product.id, current_user().id,
                     {'saldo': request.form.get('balance')}, request.remote_addr)
        db.session.commit()
        flash('Saldo ajustado e movimentacao registrada.', 'success')
    except ValueError as exc:
        db.session.rollback(); flash(str(exc), 'error')
    return redirect(url_for('operations.inventory'))


@operations_bp.post('/os/<int:work_order_id>/reservar-pecas')
@login_required
@permission_required('inventory.move')
def reserve_parts(work_order_id):
    order = db.get_or_404(WorkOrder, work_order_id)
    try:
        reservations = reserve_order_parts(order)
        record_audit('RESERVAR_ESTOQUE', 'OS', order.id, current_user().id,
                     {'reservas': len(reservations)}, request.remote_addr)
        db.session.commit(); flash(f'{len(reservations)} item(ns) reservado(s).', 'success')
    except ValueError as exc:
        db.session.rollback(); flash(str(exc), 'error')
    return redirect(url_for('web.work_orders_show', work_order_id=order.id))


@operations_bp.post('/os/<int:work_order_id>/liberar-reservas')
@login_required
@permission_required('inventory.move')
def release_parts(work_order_id):
    order = db.get_or_404(WorkOrder, work_order_id)
    count = release_order_reservations(order)
    record_audit('LIBERAR_ESTOQUE', 'OS', order.id, current_user().id, {'reservas': count}, request.remote_addr)
    db.session.commit(); flash(f'{count} reserva(s) liberada(s).', 'success')
    return redirect(url_for('web.work_orders_show', work_order_id=order.id))


@operations_bp.get('/auditoria')
@login_required
@admin_required
def audit_log():
    from ..business_reports import history
    return history()
