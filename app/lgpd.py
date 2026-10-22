"""LGPD: exportação dos dados da oficina e, por cliente, exportação e anonimização dos dados pessoais."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime

from flask import Blueprint, flash, redirect, request, send_file, url_for

from .auth import admin_required, current_user, login_required
from .fleet.models import Vehicle
from .models import Budget, Client, FinancialEntry, PaymentMethod, Product, Service, WorkOrder, WorkOrderItem, db
from .operations.services import record_audit

lgpd_bp = Blueprint('lgpd', __name__, url_prefix='/dados')

EXPORT_MODELS = (Client, Vehicle, Service, Product, PaymentMethod, Budget, WorkOrder, WorkOrderItem, FinancialEntry)


def _cell(value):
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@') else text  # planilha não executa fórmula vinda do cadastro


@lgpd_bp.get('/exportar')
@login_required
@admin_required
def export_all():
    """Todos os dados da oficina em CSV (um arquivo por tabela). Funciona mesmo com a assinatura suspensa."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for model in EXPORT_MODELS:
            columns = [column.key for column in model.__table__.columns]
            text = io.StringIO()
            writer = csv.writer(text, delimiter=';')
            writer.writerow(columns)
            for row in db.session.query(model).order_by(model.__table__.primary_key.columns.values()[0]).yield_per(500):
                writer.writerow([_cell(getattr(row, column)) for column in columns])
            archive.writestr(f'{model.__tablename__}.csv', '﻿' + text.getvalue())
    record_audit('EXPORTAR_DADOS', 'SISTEMA', None, current_user().id, {'tabelas': [m.__tablename__ for m in EXPORT_MODELS]},
                 request.remote_addr)
    db.session.commit()
    buffer.seek(0)
    return send_file(buffer, mimetype='application/zip', as_attachment=True,
                     download_name=f'lshub-dados-{datetime.now():%Y%m%d-%H%M}.zip')


@lgpd_bp.get('/clientes/<int:client_id>/exportar')
@login_required
@admin_required
def export_client(client_id: int):
    """Atende ao pedido de acesso do titular (LGPD art. 18): tudo o que a oficina guarda sobre ele."""
    client = db.get_or_404(Client, client_id)
    data = {
        'cliente': client.to_dict(),
        'veiculos': [vehicle.to_dict() for vehicle in Vehicle.query.filter_by(client_id=client.id)],
        'orcamentos': [budget.to_dict() for budget in client.budgets],
        'ordens_servico': [dict(order.to_dict(), itens=[item.to_dict() for item in order.items]) for order in client.work_orders],
        'gerado_em': datetime.now().isoformat(timespec='seconds'),
    }
    record_audit('EXPORTAR_TITULAR', 'CLIENTE', client.id, current_user().id, None, request.remote_addr)
    db.session.commit()
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode('utf-8')
    return send_file(io.BytesIO(payload), mimetype='application/json', as_attachment=True,
                     download_name=f'dados-cliente-{client.id}.json')


@lgpd_bp.post('/clientes/<int:client_id>/anonimizar')
@login_required
@admin_required
def anonymize_client(client_id: int):
    """Atende ao pedido de eliminação: apaga os dados pessoais e mantém O.S., financeiro e notas,
    que a oficina precisa guardar por obrigação legal e fiscal (LGPD art. 16, I)."""
    client = db.get_or_404(Client, client_id)
    if (request.form.get('confirmacao') or '').strip().upper() != 'ANONIMIZAR':
        flash('Digite ANONIMIZAR para confirmar. Esta ação não pode ser desfeita.', 'error')
        return redirect(url_for('web.clients_show', client_id=client.id))
    label = f'Cliente anonimizado #{client.id}'
    client.nome = label
    client.cpf_cnpj = client.inscricao_estadual = client.telefone = client.email = client.endereco = client.observacoes = None
    for vehicle in Vehicle.query.filter_by(client_id=client.id):
        vehicle.chassi = vehicle.renavam = vehicle.observacoes = None
    WorkOrder.query.filter_by(client_id=client.id).update({'client_nome': label}, synchronize_session=False)
    record_audit('ANONIMIZAR', 'CLIENTE', client.id, current_user().id, {'motivo': 'pedido do titular (LGPD)'}, request.remote_addr)
    db.session.commit()
    flash('Dados pessoais do cliente anonimizados. O histórico de O.S. e financeiro foi mantido.', 'success')
    return redirect(url_for('web.clients_show', client_id=client.id))

