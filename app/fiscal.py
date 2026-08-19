from __future__ import annotations

import base64
import json
import os
from datetime import date
from decimal import Decimal
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from .models import BankAccount, Client, Employee, FinancialEntry, FiscalApiConfig, FiscalDocument, PaymentMethod, Product, WorkOrder, db
from .services import next_number
from .utils import parse_date, parse_decimal
from .settings import get_system_settings


def get_fiscal_config() -> FiscalApiConfig | None:
    config = FiscalApiConfig.query.order_by(FiscalApiConfig.id.asc()).first()
    if config:
        env_token = _focus_env_token()
        if config.provider_name == 'FOCUSNFE' and env_token:
            config.api_token = env_token
            config.environment = _focus_env_environment()
            config.api_base_url = os.getenv('FOCUS_NFE_BASE_URL') or _focus_base_url(config.environment)
            db.session.add(config)
            db.session.flush()
        return config
    if not _focus_env_token():
        return None
    config = FiscalApiConfig(
        provider_name='FOCUSNFE',
        environment=_focus_env_environment(),
        api_base_url=os.getenv('FOCUS_NFE_BASE_URL') or _focus_base_url(_focus_env_environment()),
        api_token=_focus_env_token(),
        company_name=os.getenv('FOCUS_NFE_COMPANY_NAME'),
        company_document=os.getenv('FOCUS_NFE_COMPANY_DOCUMENT'),
        municipal_registration=os.getenv('FOCUS_NFE_MUNICIPAL_REGISTRATION'),
        state_registration=os.getenv('FOCUS_NFE_STATE_REGISTRATION'),
        tax_regime=os.getenv('FOCUS_NFE_TAX_REGIME'),
        default_service_code=os.getenv('FOCUS_NFE_DEFAULT_SERVICE_CODE'),
        default_nature=os.getenv('FOCUS_NFE_DEFAULT_NATURE') or 'Venda',
        webhook_url=os.getenv('FOCUS_NFE_WEBHOOK_URL'),
        active=True,
    )
    db.session.add(config)
    db.session.flush()
    return config


def save_fiscal_config_from_form(form) -> FiscalApiConfig:
    config = get_fiscal_config() or FiscalApiConfig()
    config.provider_name = (form.get('provider_name') or 'CUSTOM').strip().upper()
    config.environment = (form.get('environment') or 'HOMOLOGACAO').strip().upper()
    api_base_url = (form.get('api_base_url') or '').strip()
    if config.provider_name == 'FOCUSNFE' and not api_base_url:
        api_base_url = _focus_base_url(config.environment)
    config.api_base_url = api_base_url or None
    api_token = (form.get('api_token') or '').strip()
    if api_token:
        config.api_token = api_token
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


def build_work_order_invoice_payload(order: WorkOrder, config: FiscalApiConfig | None = None, document_type: str | None = None) -> dict[str, Any]:
    client = order.client
    service_items = []
    part_items = []
    for item in order.items:
        target = service_items if item.item_type == 'SERVICO' else part_items
        product = db.session.get(Product, item.reference_id) if item.item_type != 'SERVICO' and item.reference_id else None
        target.append({
            'descricao': item.descricao,
            'quantidade': float(parse_decimal(item.quantidade)),
            'valor_unitario': float(parse_decimal(item.valor_unitario)),
            'desconto': float(parse_decimal(item.desconto)),
            'total': float(parse_decimal(item.total)),
            'reference_id': item.reference_id,
            'unidade': product.unidade if product and product.unidade else 'UN',
            'ncm': product.ncm if product else None,
            'cfop': product.cfop if product else None,
        })

    document_type = document_type or ('NFSE' if service_items else 'NFE')
    if document_type == 'NFSE':
        part_items = []
    elif document_type == 'NFE':
        service_items = []
    return {
        'document_type': document_type,
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
            'data_saida': order.data_saida.isoformat() if order.data_saida else None,
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


def create_or_update_fiscal_document(order: WorkOrder, config: FiscalApiConfig | None = None, document_type: str | None = None) -> FiscalDocument:
    payload = build_work_order_invoice_payload(order, config, document_type)
    document = FiscalDocument.query.filter_by(work_order_id=order.id, document_type=payload['document_type']).order_by(FiscalDocument.id.desc()).first()
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
    if config.provider_name == 'FOCUSNFE':
        if document.document_type == 'NFSE':
            return issue_with_focus_nfse(document, config)
        return issue_with_focus_nfe(document, config)

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


def _focus_base_url(environment: str | None) -> str:
    if (environment or '').upper() == 'PRODUCAO':
        return 'https://api.focusnfe.com.br'
    return 'https://homologacao.focusnfe.com.br'


def _focus_env_token() -> str | None:
    environment = _focus_env_environment()
    environment_token = (
        os.getenv(f'FOCUS_NFE_TOKEN_{environment}')
        or os.getenv(f'FOCUSNFE_TOKEN_{environment}')
    )
    return (
        environment_token
        or os.getenv('FOCUS_NFE_TOKEN_PRINCIPAL')
        or os.getenv('FOCUSNFE_TOKEN_PRINCIPAL')
        or os.getenv('FOCUS_NFE_TOKEN')
        or os.getenv('FOCUSNFE_TOKEN')
    )


def _focus_env_environment() -> str:
    return (os.getenv('FOCUS_NFE_ENVIRONMENT') or os.getenv('FOCUSNFE_ENVIRONMENT') or 'HOMOLOGACAO').strip().upper()


def _focus_authorization_header(token: str | None) -> str:
    if not token:
        raise ValueError('Configure o token da Focus NFe antes de emitir.')
    encoded = base64.b64encode(f'{token}:'.encode('utf-8')).decode('ascii')
    return f'Basic {encoded}'


def _focus_url(config: FiscalApiConfig, path: str, params: dict[str, str] | None = None) -> str:
    base_url = (config.api_base_url or _focus_base_url(config.environment)).rstrip('/')
    url = f'{base_url}{path}'
    if params:
        url = f'{url}?{urlencode(params)}'
    return url


def _digits(value: str | None) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def _split_address(address: str | None) -> dict[str, str | None]:
    if not address:
        return {'logradouro': None, 'numero': None, 'bairro': None}
    parts = [part.strip() for part in address.split(',') if part.strip()]
    return {
        'logradouro': parts[0] if parts else address,
        'numero': parts[1] if len(parts) > 1 else 'S/N',
        'bairro': parts[2] if len(parts) > 2 else None,
    }


def _nfse_nature_code(value: str | None) -> str:
    labels = {
        'Tributação no município': '1',
        'Tributacao no municipio': '1',
        'Tributação fora do município': '2',
        'Tributacao fora do municipio': '2',
        'Isenção': '3',
        'Isencao': '3',
        'Imune': '4',
        'Exigibilidade suspensa por decisão judicial': '5',
        'Exigibilidade suspensa por procedimento administrativo': '6',
    }
    candidate = str(value or '').strip()
    return labels.get(candidate, candidate if candidate in {'1', '2', '3', '4', '5', '6'} else '1')


def _focus_iso_datetime(value: str | None) -> str | None:
    candidate = str(value or '').strip()
    if not candidate:
        return None
    return candidate if 'T' in candidate else f'{candidate}T00:00:00-03:00'


def _without_empty_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: cleaned for key, item in value.items() if (cleaned := _without_empty_values(item)) not in (None, '', [], {})}
    if isinstance(value, list):
        return [cleaned for item in value if (cleaned := _without_empty_values(item)) not in (None, '', [], {})]
    return value


def build_focus_nfe_payload(document: FiscalDocument) -> dict[str, Any]:
    payload = json.loads(document.request_payload or '{}')
    customer = payload.get('customer') or {}
    work_order = payload.get('work_order') or {}
    totals = payload.get('totals') or {}
    invoice = payload.get('invoice') or {}
    parts = payload.get('items', {}).get('parts') or []
    services = payload.get('items', {}).get('services') or []
    settings = get_system_settings()
    fiscal_config = FiscalApiConfig.query.order_by(FiscalApiConfig.id.asc()).first()
    issuer_document = _digits((fiscal_config.company_document if fiscal_config else None) or settings.company_document)
    issuer_state_registration = (fiscal_config.state_registration if fiscal_config else None) or None
    customer_document = _digits(customer.get('documento'))
    customer_address = _split_address(customer.get('endereco'))
    company_address = _split_address(settings.address)
    issue_date = _focus_iso_datetime(invoice.get('data_emissao') or work_order.get('data_entrada') or date.today().isoformat())

    focus_payload: dict[str, Any] = {
        'natureza_operacao': invoice.get('natureza_operacao') or payload.get('defaults', {}).get('natureza_operacao') or 'Venda',
        'data_emissao': issue_date,
        'cnpj_emitente': issuer_document or None,
        'inscricao_estadual_emitente': issuer_state_registration,
        'data_entrada_saida': _focus_iso_datetime(invoice.get('data_saida')),
        'tipo_documento': int(invoice.get('tipo_documento') or 1),
        'local_destino': int(invoice.get('destino_operacao') or 1),
        'finalidade_emissao': int(invoice.get('finalidade_emissao') or 1),
        'nome_destinatario': customer.get('nome'),
        'telefone_destinatario': _digits(customer.get('telefone')) or None,
        'logradouro_destinatario': customer_address['logradouro'],
        'numero_destinatario': customer_address['numero'],
        'bairro_destinatario': customer_address['bairro'],
        'valor_frete': invoice.get('valor_frete') or 0,
        'valor_seguro': invoice.get('valor_seguro') or 0,
        'valor_desconto': invoice.get('valor_desconto') or 0,
        'valor_outras_despesas': invoice.get('valor_despesas') or 0,
        'valor_total': totals.get('geral'),
        'valor_produtos': totals.get('pecas') or totals.get('geral'),
        'modalidade_frete': int(invoice.get('modalidade_frete') or 9),
        'presenca_comprador': int(invoice.get('tipo_atendimento') or 0),
        'items': [],
    }
    if invoice.get('chave_referenciada'):
        focus_payload['notas_referenciadas'] = [{'chave_nfe': _digits(invoice['chave_referenciada'])}]
    if len(customer_document) == 14:
        focus_payload['cnpj_destinatario'] = customer_document
    elif len(customer_document) == 11:
        focus_payload['cpf_destinatario'] = customer_document

    for index, item in enumerate(parts + services, start=1):
        total = parse_decimal(item.get('total'))
        quantity = parse_decimal(item.get('quantidade')) or Decimal('1')
        unit_value = parse_decimal(item.get('valor_unitario')) or (total / quantity if quantity else total)
        focus_payload['items'].append(
            {
                'numero_item': index,
                'codigo_produto': item.get('reference_id') or index,
                'descricao': item.get('descricao'),
                'cfop': item.get('cfop') or '5102',
                'unidade_comercial': item.get('unidade') or 'UN',
                'quantidade_comercial': float(quantity),
                'valor_unitario_comercial': float(unit_value),
                'valor_unitario_tributavel': float(unit_value),
                'unidade_tributavel': 'UN',
                'quantidade_tributavel': float(quantity),
                'valor_bruto': float(total),
                'codigo_ncm': _digits(item.get('ncm')),
                'icms_situacao_tributaria': '102',
                'icms_origem': 0,
                'pis_situacao_tributaria': '07',
                'cofins_situacao_tributaria': '07',
            }
        )
    return _without_empty_values(focus_payload)


def apply_invoice_form(document: FiscalDocument, form) -> None:
    payload = json.loads(document.request_payload or '{}')
    payload['invoice'] = {
        'natureza_operacao': (form.get('natureza_operacao') or '').strip(),
        'tipo_documento': form.get('tipo_documento') or '1',
        'finalidade_emissao': form.get('finalidade_emissao') or '1',
        'serie': (form.get('serie') or '').strip(),
        'modalidade_frete': form.get('modalidade_frete') or '9',
        'valor_frete': form.get('valor_frete') or '0',
        'valor_seguro': form.get('valor_seguro') or '0',
        'valor_desconto': form.get('valor_desconto') or '0',
        'valor_despesas': form.get('valor_despesas') or '0',
        'base_icms': form.get('base_icms') or '0',
        'valor_icms': form.get('valor_icms') or '0',
        'base_icms_st': form.get('base_icms_st') or '0',
        'valor_icms_st': form.get('valor_icms_st') or '0',
        'valor_ipi': form.get('valor_ipi') or '0',
        'data_emissao': form.get('data_emissao') or date.today().isoformat(),
        'data_saida': form.get('data_saida') or '',
        'hora_saida': form.get('hora_saida') or '',
        'chave_referenciada': form.get('chave_referenciada') or '',
        'quantidade_parcelas': form.get('quantidade_parcelas') or '1',
        'forma_pagamento': (form.get('forma_pagamento') or '').strip(),
        'transportadora': (form.get('transportadora') or '').strip(),
        'placa_veiculo': (form.get('placa_veiculo') or '').strip(),
        'uf_veiculo': (form.get('uf_veiculo') or '').strip().upper(),
        'peso_bruto': form.get('peso_bruto') or '0',
        'peso_liquido': form.get('peso_liquido') or '0',
        'volumes': form.get('volumes') or '0',
        'especie': (form.get('especie') or '').strip(),
        'marca': (form.get('marca') or '').strip(),
        'numeracao': (form.get('numeracao') or '').strip(),
        'rntrc': (form.get('rntrc') or '').strip(),
        'ordem_compra': (form.get('ordem_compra') or '').strip(),
        'tipo_atendimento': form.get('tipo_atendimento') or '0',
        'destino_operacao': form.get('destino_operacao') or '1',
        'observacoes': (form.get('observacoes') or '').strip(),
        'informacoes_fisco': (form.get('informacoes_fisco') or '').strip(),
        'observacoes_internas': (form.get('observacoes_internas') or '').strip(),
        'item_lista_servico': form.get('item_lista_servico') or '',
        'service_description': form.get('service_description') or '',
        'iss_retido': form.get('iss_retido') or 'false',
        'aliquota': form.get('aliquota') or '0',
        'valor_iss_retido': form.get('valor_iss_retido') or '0',
    }
    ipi_rates = form.getlist('item_ipi_percent')
    icms_rates = form.getlist('item_icms_percent')
    for index, item in enumerate((payload.get('items', {}).get('parts') or []) + (payload.get('items', {}).get('services') or [])):
        item['ncm'] = (form.getlist('item_ncm')[index] if index < len(form.getlist('item_ncm')) else '').strip()
        item['cfop'] = (form.getlist('item_cfop')[index] if index < len(form.getlist('item_cfop')) else '5102').strip()
        item['unidade'] = (form.getlist('item_unidade')[index] if index < len(form.getlist('item_unidade')) else 'UN').strip() or 'UN'
        item['ipi_percent'] = str(ipi_rates[index] if index < len(ipi_rates) else item.get('ipi_percent') or '0').strip()
        item['icms_percent'] = str(icms_rates[index] if index < len(icms_rates) else item.get('icms_percent') or '0').strip()
    if form.get('serie'):
        document.serie = (form.get('serie') or '').strip()
    document.request_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    db.session.add(document)


def create_parts_fiscal_document(form, config: FiscalApiConfig | None = None) -> FiscalDocument:
    descriptions = form.getlist('item_descricao')
    quantities = form.getlist('item_quantidade')
    prices = form.getlist('item_valor_unitario')
    codes = form.getlist('item_codigo')
    items = []
    for index, description in enumerate(descriptions):
        description = description.strip()
        if not description:
            continue
        quantity = parse_decimal(quantities[index] if index < len(quantities) else '1') or Decimal('1')
        price = parse_decimal(prices[index] if index < len(prices) else '0')
        items.append({
            'descricao': description,
            'quantidade': float(quantity),
            'valor_unitario': float(price),
            'total': float(quantity * price),
            'reference_id': codes[index].strip() if index < len(codes) else '',
            'ncm': '',
            'cfop': '5102',
            'unidade': 'UN',
        })
    total = sum(Decimal(str(item['total'])) for item in items)
    payload = {
        'document_type': 'NFE',
        'environment': config.environment if config else 'HOMOLOGACAO',
        'provider': config.provider_name if config else 'CUSTOM',
        'company': {},
        'work_order': {},
        'customer': {
            'nome': (form.get('cliente_nome') or '').strip(),
            'documento': (form.get('cliente_documento') or '').strip(),
            'telefone': (form.get('cliente_telefone') or '').strip(),
            'endereco': (form.get('cliente_endereco') or '').strip(),
        },
        'source_xml_id': form.get('xml_import_id') or None,
        'items': {'services': [], 'parts': items},
        'totals': {'servicos': 0, 'pecas': float(total), 'geral': float(total)},
        'defaults': {'natureza_operacao': (form.get('natureza_operacao') or 'Venda de mercadoria').strip()},
    }
    document = FiscalDocument(
        work_order_id=None,
        provider_name=payload['provider'],
        environment=payload['environment'],
        document_type='NFE',
        numero=next_number(FiscalDocument, 'NF', field='numero'),
        request_payload=json.dumps(payload, ensure_ascii=False, indent=2),
        status='PRONTO_PARA_ENVIO',
    )
    db.session.add(document)
    db.session.flush()
    return document


def issue_with_focus_nfe(document: FiscalDocument, config: FiscalApiConfig) -> FiscalDocument:
    focus_payload = build_focus_nfe_payload(document)
    ref = document.external_id or document.numero or f'os-{document.work_order_id}'
    data = json.dumps(focus_payload, ensure_ascii=False).encode('utf-8')
    req = urlrequest.Request(
        _focus_url(config, '/v2/nfe', {'ref': ref}),
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': _focus_authorization_header(config.api_token),
        },
        method='POST',
    )
    document.external_id = ref
    return _send_focus_request(document, req)


def build_focus_nfse_payload(document: FiscalDocument, config: FiscalApiConfig) -> dict[str, Any]:
    payload = json.loads(document.request_payload or '{}')
    customer = payload.get('customer') or {}
    totals = payload.get('totals') or {}
    services = payload.get('items', {}).get('services') or []
    invoice = payload.get('invoice') or {}
    company = get_focus_company(config)
    customer_document = _digits(customer.get('documento'))
    service_description = invoice.get('service_description') or '\n'.join(item.get('descricao') or '' for item in services).strip()
    service_code = invoice.get('item_lista_servico') or config.default_service_code
    if not service_code:
        raise ValueError('Informe o código do serviço municipal antes de emitir a NFS-e.')
    if not company.get('codigo_municipio'):
        raise ValueError('O cadastro da empresa na Focus NFe não possui o código do município para emitir a NFS-e.')
    prestador = {
        'cnpj': _digits(company.get('cnpj')),
        'inscricao_municipal': company.get('inscricao_municipal'),
        'codigo_municipio': company.get('codigo_municipio'),
    }
    tomador: dict[str, Any] = {
        'razao_social': customer.get('nome'),
        'telefone': _digits(customer.get('telefone')) or None,
        'email': customer.get('email'),
    }
    customer_address = _split_address(customer.get('endereco'))
    if customer_address['logradouro']:
        tomador['endereco'] = {
            'logradouro': customer_address['logradouro'],
            'numero': customer_address['numero'],
            'bairro': customer_address['bairro'],
        }
    if len(customer_document) == 14:
        tomador['cnpj'] = customer_document
    elif len(customer_document) == 11:
        tomador['cpf'] = customer_document
    else:
        raise ValueError('O cliente precisa ter CPF ou CNPJ válido para emitir NFS-e.')
    return _without_empty_values({
        'data_emissao': _focus_iso_datetime(invoice.get('data_emissao') or date.today().isoformat()),
        'natureza_operacao': _nfse_nature_code(invoice.get('natureza_operacao')),
        'optante_simples_nacional': int(company.get('regime_tributario') or 1) == 1,
        'prestador': prestador,
        'tomador': tomador,
        'servico': {
            'valor_servicos': totals.get('servicos') or totals.get('geral'),
            'valor_deducoes': 0,
            'iss_retido': invoice.get('iss_retido') in {True, 'true', '1', 1},
            'item_lista_servico': service_code,
            'codigo_municipio': company.get('codigo_municipio'),
            'discriminacao': service_description or 'Serviços automotivos',
            'valor_iss': invoice.get('valor_iss') or 0,
            'valor_iss_retido': invoice.get('valor_iss_retido') or 0,
            'base_calculo': totals.get('servicos') or totals.get('geral'),
            'aliquota': invoice.get('aliquota') or 0,
        },
    })


def get_focus_company(config: FiscalApiConfig) -> dict[str, Any]:
    _, body = _focus_json_request(config, '/v2/empresas')
    try:
        response = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError('A Focus NFe não retornou o cadastro da empresa.') from exc
    if isinstance(response, list):
        company = response[0] if response else {}
    else:
        company = (response.get('empresas') or [response])[0] if isinstance(response, dict) else {}
    if not company.get('cnpj') or not company.get('inscricao_municipal'):
        raise ValueError('A empresa da Focus NFe não possui CNPJ e inscrição municipal cadastrados.')
    return company


def issue_with_focus_nfse(document: FiscalDocument, config: FiscalApiConfig) -> FiscalDocument:
    focus_payload = build_focus_nfse_payload(document, config)
    ref = document.external_id or document.numero or f'os-{document.work_order_id}'
    data = json.dumps(focus_payload, ensure_ascii=False).encode('utf-8')
    req = urlrequest.Request(
        _focus_url(config, '/v2/nfse', {'ref': ref}),
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': _focus_authorization_header(config.api_token),
        },
        method='POST',
    )
    document.external_id = ref
    return _send_focus_request(document, req)


def _focus_json_request(config: FiscalApiConfig, path: str, method: str = 'GET', payload: dict[str, Any] | None = None) -> tuple[int, str]:
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
    req = urlrequest.Request(
        _focus_url(config, path),
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': _focus_authorization_header(config.api_token),
        },
        method=method,
    )
    try:
        with urlrequest.urlopen(req, timeout=30) as response:
            return response.status, response.read().decode('utf-8')
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore')
        raise ValueError(f'Focus NFe retornou HTTP {exc.code}: {body}') from exc
    except URLError as exc:
        raise ValueError(f'Falha ao conectar na Focus NFe: {exc.reason}') from exc


def _consult_focus_document(document: FiscalDocument, config: FiscalApiConfig, resource: str) -> FiscalDocument:
    if not document.external_id:
        raise ValueError('A nota ainda não possui uma referência enviada à Focus NFe.')
    _, body = _focus_json_request(config, f'/v2/{resource}/{document.external_id}')
    document.response_payload = body
    try:
        response = json.loads(body)
    except json.JSONDecodeError:
        response = {}
    document.status = str(response.get('status') or document.status or 'CONSULTADO').upper()
    document.access_key = response.get('chave_nfe') or response.get('chave') or response.get('access_key') or document.access_key
    document.pdf_url = response.get('url_danfe') or response.get('danfe_url') or response.get('pdf_url') or document.pdf_url
    response_xml = response.get('xml')
    if isinstance(response_xml, str) and response_xml.lstrip().startswith('<'):
        document.xml_content = response_xml
    db.session.add(document)
    db.session.flush()
    return document


def consult_focus_nfe(document: FiscalDocument, config: FiscalApiConfig) -> FiscalDocument:
    return _consult_focus_document(document, config, 'nfe')


def consult_focus_nfse(document: FiscalDocument, config: FiscalApiConfig) -> FiscalDocument:
    return _consult_focus_document(document, config, 'nfse')


def _cancel_focus_document(document: FiscalDocument, config: FiscalApiConfig, justification: str, resource: str) -> FiscalDocument:
    if not document.external_id:
        raise ValueError('A nota ainda não possui uma referência enviada à Focus NFe.')
    justification = (justification or '').strip()
    if len(justification) < 15 or len(justification) > 255:
        raise ValueError('A justificativa do cancelamento deve ter entre 15 e 255 caracteres.')
    _, body = _focus_json_request(
        config,
        f'/v2/{resource}/{document.external_id}',
        method='DELETE',
        payload={'justificativa': justification},
    )
    document.response_payload = body
    try:
        response = json.loads(body)
    except json.JSONDecodeError:
        response = {}
    response_status = str(response.get('status') or '').lower()
    if response_status in {'erro_cancelamento', 'erro'}:
        errors = response.get('erros') or []
        details = '; '.join(str(error.get('mensagem') or error) for error in errors if isinstance(error, dict))
        raise ValueError(details or 'A Focus NFe não autorizou o cancelamento.')
    if response_status not in {'cancelado', 'cancelada'}:
        raise ValueError(str(response.get('mensagem') or 'A Focus NFe não confirmou o cancelamento.'))
    document.status = 'CANCELADO'
    db.session.add(document)
    db.session.flush()
    return document


def cancel_focus_nfe(document: FiscalDocument, config: FiscalApiConfig, justification: str) -> FiscalDocument:
    return _cancel_focus_document(document, config, justification, 'nfe')


def cancel_focus_nfse(document: FiscalDocument, config: FiscalApiConfig, justification: str) -> FiscalDocument:
    return _cancel_focus_document(document, config, justification, 'nfse')


def import_nfe_xml_to_focus(xml_content: bytes | str, config: FiscalApiConfig, ref: str | None = None) -> dict[str, Any]:
    if config.provider_name != 'FOCUSNFE':
        raise ValueError('A importação via API está disponível para o provedor Focus NFe.')
    raw_xml = xml_content.encode('utf-8') if isinstance(xml_content, str) else xml_content
    req = urlrequest.Request(
        _focus_url(config, '/v2/nfe/importacao', {'ref': ref} if ref else None),
        data=raw_xml,
        headers={
            'Content-Type': 'application/xml',
            'Accept': 'application/json',
            'Authorization': _focus_authorization_header(config.api_token),
        },
        method='POST',
    )
    try:
        with urlrequest.urlopen(req, timeout=30) as response:
            body = response.read().decode('utf-8')
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore')
        raise ValueError(f'Focus NFe retornou HTTP {exc.code}: {body}') from exc
    except URLError as exc:
        raise ValueError(f'Falha ao conectar na Focus NFe: {exc.reason}') from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {'response': body}


def _send_focus_request(document: FiscalDocument, req: urlrequest.Request) -> FiscalDocument:
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
        raise ValueError(f'Falha ao conectar na Focus NFe: {exc.reason}') from exc

    document.response_payload = body
    document.status = 'ENVIADO'
    document.error_message = None
    try:
        response_json = json.loads(body)
    except json.JSONDecodeError:
        response_json = {}

    document.access_key = response_json.get('chave_nfe') or response_json.get('chave') or response_json.get('access_key')
    document.pdf_url = response_json.get('url_danfe') or response_json.get('danfe_url') or response_json.get('pdf_url')
    response_xml = response_json.get('xml')
    if isinstance(response_xml, str) and response_xml.lstrip().startswith('<'):
        document.xml_content = response_xml
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
            numero = next_number(WorkOrder, get_system_settings().work_order_prefix or 'OS')
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
