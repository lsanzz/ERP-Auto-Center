from __future__ import annotations

import base64
import json
from decimal import Decimal
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from xml.sax.saxutils import escape

from .models import BankAccount, Client, Employee, FinancialEntry, FiscalApiConfig, FiscalDocument, PaymentMethod, WorkOrder, db
from .services import next_number
from .utils import parse_date, parse_decimal


def get_fiscal_config() -> FiscalApiConfig | None:
    return FiscalApiConfig.query.order_by(FiscalApiConfig.id.asc()).first()


def save_fiscal_config_from_form(form) -> FiscalApiConfig:
    config = get_fiscal_config() or FiscalApiConfig()
    config.provider_name = (form.get('provider_name') or 'CUSTOM').strip().upper()
    config.environment = (form.get('environment') or 'HOMOLOGACAO').strip().upper()
    config.api_base_url = (form.get('api_base_url') or '').strip() or None
    config.api_token = (form.get('api_token') or '').strip() or None
    config.company_name = (form.get('company_name') or '').strip() or None
    config.company_document = (form.get('company_document') or '').strip() or None
    config.municipal_registration = (form.get('municipal_registration') or '').strip() or None
    config.state_registration = (form.get('state_registration') or '').strip() or None
    config.tax_regime = (form.get('tax_regime') or '').strip() or None
    config.default_service_code = (form.get('default_service_code') or '').strip() or None
    config.default_nature = (form.get('default_nature') or '').strip() or None
    config.webhook_url = (form.get('webhook_url') or '').strip() or None
    config.active = bool(form.get('active'))
    db.session.add(config)
    db.session.flush()
    return config


def build_work_order_invoice_payload(order: WorkOrder, config: FiscalApiConfig | None = None) -> dict[str, Any]:
    client = order.client
    service_items = []
    part_items = []
    for item in order.items:
        target = service_items if item.item_type == 'SERVICO' else part_items
        target.append({
            'descricao': item.descricao,
            'quantidade': float(parse_decimal(item.quantidade)),
            'valor_unitario': float(parse_decimal(item.valor_unitario)),
            'desconto': float(parse_decimal(item.desconto)),
            'total': float(parse_decimal(item.total)),
            'reference_id': item.reference_id,
        })

    return {
        'document_type': 'NFSE' if service_items else 'NFE',
        'environment': (config.environment if config else 'HOMOLOGACAO'),
        'provider': (config.provider_name if config else 'CUSTOM'),
        'company': {
            'nome': config.company_name if config else None,
            'documento': config.company_document if config else None,
            'inscricao_municipal': config.municipal_registration if config else None,
            'inscricao_estadual': config.state_registration if config else None,
            'regime_tributario': config.tax_regime if config else None,
        },
        'work_order': {
            'id': order.id,
            'numero': order.numero,
            'status': order.status,
            'data_entrada': order.data_entrada.isoformat() if order.data_entrada else None,
            'placa': order.placa,
            'veiculo_descricao': order.veiculo_descricao,
            'observacoes': order.observacoes,
        },
        'customer': {
            'nome': order.client_nome or (client.nome if client else None),
            'documento': client.cpf_cnpj if client else None,
            'email': client.email if client else None,
            'telefone': client.telefone if client else None,
            'endereco': client.endereco if client else None,
        },
        'items': {
            'services': service_items,
            'parts': part_items,
        },
        'totals': {
            'servicos': float(parse_decimal(order.total_servicos)),
            'pecas': float(parse_decimal(order.total_pecas)),
            'geral': float(parse_decimal(order.total_geral)),
        },
        'payment': {
            'forma_pagamento': order.payment_method.nome if order.payment_method else None,
            'parcelas': order.installment_count or 1,
        },
        'defaults': {
            'service_code': config.default_service_code if config else None,
            'natureza_operacao': config.default_nature if config else None,
        },
    }


def build_internal_xml(payload: dict[str, Any]) -> str:
    customer = payload.get('customer') or {}
    wo = payload.get('work_order') or {}
    totals = payload.get('totals') or {}
    parts = payload.get('items', {}).get('parts') or []
    services = payload.get('items', {}).get('services') or []

    def row(tag: str, value: Any) -> str:
        return f'<{tag}>{escape(str(value or ""))}</{tag}>'

    service_xml = ''.join(
        '<service>'
        + row('descricao', item.get('descricao'))
        + row('quantidade', item.get('quantidade'))
        + row('valor_unitario', item.get('valor_unitario'))
        + row('total', item.get('total'))
        + '</service>'
        for item in services
    )
    part_xml = ''.join(
        '<part>'
        + row('descricao', item.get('descricao'))
        + row('quantidade', item.get('quantidade'))
        + row('valor_unitario', item.get('valor_unitario'))
        + row('total', item.get('total'))
        + '</part>'
        for item in parts
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<fiscalDocument>'
        + row('documentType', payload.get('document_type'))
        + row('provider', payload.get('provider'))
        + '<workOrder>'
        + row('id', wo.get('id'))
        + row('numero', wo.get('numero'))
        + row('placa', wo.get('placa'))
        + row('veiculo', wo.get('veiculo_descricao'))
        + '</workOrder>'
        + '<customer>'
        + row('nome', customer.get('nome'))
        + row('documento', customer.get('documento'))
        + row('email', customer.get('email'))
        + '</customer>'
        + '<totals>'
        + row('servicos', totals.get('servicos'))
        + row('pecas', totals.get('pecas'))
        + row('geral', totals.get('geral'))
        + '</totals>'
        + '<services>' + service_xml + '</services>'
        + '<parts>' + part_xml + '</parts>'
        + '</fiscalDocument>'
    )


def create_or_update_fiscal_document(order: WorkOrder, config: FiscalApiConfig | None = None) -> FiscalDocument:
    document = FiscalDocument.query.filter_by(work_order_id=order.id).order_by(FiscalDocument.id.desc()).first()
    payload = build_work_order_invoice_payload(order, config)
    xml_content = build_internal_xml(payload)
    if not document:
        document = FiscalDocument(
            work_order_id=order.id,
            provider_name=(config.provider_name if config else 'CUSTOM'),
            environment=(config.environment if config else 'HOMOLOGACAO'),
            document_type=payload['document_type'],
            numero=next_number(FiscalDocument, 'NF', field='numero'),
        )
    document.provider_name = payload['provider']
    document.environment = payload['environment']
    document.document_type = payload['document_type']
    document.request_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    document.xml_content = xml_content
    document.status = 'PRONTO_PARA_ENVIO'
    db.session.add(document)
    db.session.flush()
    return document


def issue_with_external_api(document: FiscalDocument, config: FiscalApiConfig) -> FiscalDocument:
    if not config.api_base_url:
        raise ValueError('Configure a URL da API fiscal antes de emitir.')

    payload = json.loads(document.request_payload or '{}')
    data = json.dumps(payload).encode('utf-8')
    req = urlrequest.Request(
        config.api_base_url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {config.api_token}' if config.api_token else '',
        },
        method='POST',
    )
    try:
        with urlrequest.urlopen(req, timeout=30) as response:
            body = response.read().decode('utf-8')
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore')
        document.status = 'ERRO'
        document.error_message = f'HTTP {exc.code}: {body}'
        document.response_payload = body
        db.session.add(document)
        db.session.flush()
        return document
    except URLError as exc:
        raise ValueError(f'Falha ao conectar na API fiscal: {exc.reason}') from exc

    document.response_payload = body
    document.status = 'ENVIADO'
    try:
        response_json = json.loads(body)
    except json.JSONDecodeError:
        response_json = {}

    document.external_id = response_json.get('id') or response_json.get('external_id')
    document.access_key = response_json.get('access_key') or response_json.get('chave')
    document.pdf_url = response_json.get('pdf_url') or response_json.get('danfe_url')
    document.xml_content = response_json.get('xml') or document.xml_content
    if response_json.get('status'):
        document.status = str(response_json.get('status')).upper()
    db.session.add(document)
    db.session.flush()
    return document


def encode_payload(data: Any) -> str:
    return base64.b64encode(json.dumps(data, ensure_ascii=False).encode('utf-8')).decode('ascii')


def decode_payload(encoded: str) -> Any:
    return json.loads(base64.b64decode(encoded.encode('ascii')).decode('utf-8'))


def preview_external_import(data: dict[str, Any]) -> dict[str, Any]:
    work_orders = data.get('work_orders') or data.get('ordens_servico') or data.get('os') or []
    financial_entries = data.get('financial_entries') or data.get('financeiro') or []
    bank_accounts = data.get('bank_accounts') or data.get('contas_bancarias') or []
    return {
        'work_orders': work_orders,
        'financial_entries': financial_entries,
        'bank_accounts': bank_accounts,
        'summary': {
            'work_orders': len(work_orders),
            'financial_entries': len(financial_entries),
            'bank_accounts': len(bank_accounts),
        },
    }


def _find_or_create_client(nome: str | None, documento: str | None = None) -> Client:
    nome = (nome or '').strip() or 'Cliente importado'
    if documento:
        existing = Client.query.filter_by(cpf_cnpj=documento).first()
        if existing:
            return existing
    existing = Client.query.filter(db.func.lower(Client.nome) == nome.lower()).first()
    if existing:
        return existing
    client = Client(nome=nome, cpf_cnpj=documento)
    db.session.add(client)
    db.session.flush()
    return client


def _find_payment_method(method_name: str | None) -> PaymentMethod | None:
    if not method_name:
        return None
    return PaymentMethod.query.filter(db.func.lower(PaymentMethod.nome) == method_name.strip().lower()).first()


def _find_bank_account(name: str | None) -> BankAccount | None:
    if not name:
        return None
    return BankAccount.query.filter(db.func.lower(BankAccount.nome) == name.strip().lower()).first()


def import_external_payload(data: dict[str, Any]) -> dict[str, int]:
    preview = preview_external_import(data)
    created = {'work_orders': 0, 'financial_entries': 0, 'bank_accounts': 0}

    for account_data in preview['bank_accounts']:
        nome = (account_data.get('nome') or account_data.get('name') or '').strip()
        if not nome:
            continue
        existing = _find_bank_account(nome)
        if existing:
            continue
        account = BankAccount(
            nome=nome,
            banco=account_data.get('banco') or account_data.get('bank'),
            agencia=account_data.get('agencia') or account_data.get('agency'),
            conta=account_data.get('conta') or account_data.get('account'),
            saldo_inicial=parse_decimal(account_data.get('saldo_inicial') or account_data.get('opening_balance')),
            saldo_atual=parse_decimal(account_data.get('saldo_atual') or account_data.get('current_balance') or account_data.get('saldo_inicial') or account_data.get('opening_balance')),
            ativo=bool(account_data.get('ativo', True)),
        )
        db.session.add(account)
        created['bank_accounts'] += 1

    db.session.flush()

    for entry_data in preview['financial_entries']:
        descricao = (entry_data.get('descricao') or entry_data.get('description') or '').strip()
        if not descricao:
            continue
        entry = FinancialEntry(
            entry_type=(entry_data.get('entry_type') or entry_data.get('tipo') or 'RECEBER').upper(),
            descricao=descricao,
            categoria=entry_data.get('categoria') or entry_data.get('category'),
            valor=parse_decimal(entry_data.get('valor') or entry_data.get('amount')),
            vencimento=parse_date(entry_data.get('vencimento') or entry_data.get('due_date')),
            payment_receipt_at=parse_date(entry_data.get('payment_receipt_at') or entry_data.get('paid_at')),
            status=(entry_data.get('status') or 'PENDENTE').upper(),
            installment_number=int(entry_data.get('installment_number') or entry_data.get('parcela') or 1),
            installment_total=int(entry_data.get('installment_total') or entry_data.get('parcelas') or 1),
            reference_type=entry_data.get('reference_type') or entry_data.get('referencia_tipo'),
            reference_id=entry_data.get('reference_id') or entry_data.get('referencia_id'),
        )
        method = _find_payment_method(entry_data.get('payment_method') or entry_data.get('forma_pagamento'))
        bank = _find_bank_account(entry_data.get('bank_account') or entry_data.get('conta_bancaria'))
        if method:
            entry.payment_method_id = method.id
        if bank:
            entry.bank_account_id = bank.id
        db.session.add(entry)
        created['financial_entries'] += 1

    db.session.flush()

    for wo_data in preview['work_orders']:
        numero = (wo_data.get('numero') or wo_data.get('number') or '').strip()
        if not numero:
            numero = next_number(WorkOrder, 'OS')
        existing = WorkOrder.query.filter_by(numero=numero).first()
        if existing:
            continue
        client = _find_or_create_client(wo_data.get('client_nome') or wo_data.get('cliente') or wo_data.get('customer_name'), wo_data.get('cpf_cnpj') or wo_data.get('documento'))
        order = WorkOrder(
            client_id=client.id,
            client_nome=wo_data.get('client_nome') or wo_data.get('cliente') or client.nome,
            numero=numero,
            status=(wo_data.get('status') or 'ABERTA').upper(),
            data_entrada=parse_date(wo_data.get('data_entrada') or wo_data.get('opened_at')),
            data_saida=parse_date(wo_data.get('data_saida') or wo_data.get('closed_at')),
            placa=wo_data.get('placa'),
            veiculo_descricao=wo_data.get('veiculo_descricao') or wo_data.get('vehicle_description'),
            observacoes=wo_data.get('observacoes') or wo_data.get('notes'),
            installment_count=int(wo_data.get('installment_count') or wo_data.get('parcelas') or 1),
            emitir_nota=bool(wo_data.get('emitir_nota', True)),
        )
        method = _find_payment_method(wo_data.get('payment_method') or wo_data.get('forma_pagamento'))
        if method:
            order.payment_method_id = method.id
        db.session.add(order)
        db.session.flush()
        for item in wo_data.get('items') or []:
            kind = str(item.get('item_type') or item.get('tipo') or 'SERVICO').upper()
            if kind == 'PRODUTO':
                kind = 'PECA'
            from .services import add_work_order_item
            add_work_order_item(
                order,
                item_type=kind,
                reference_id=item.get('reference_id'),
                quantidade=item.get('quantidade') or item.get('quantity') or 1,
                desconto=item.get('desconto') or item.get('discount') or 0,
                descricao=item.get('descricao') or item.get('description'),
                valor_unitario=item.get('valor_unitario') or item.get('unit_price'),
                total=item.get('total'),
            )
        created['work_orders'] += 1

    db.session.flush()
    return created
