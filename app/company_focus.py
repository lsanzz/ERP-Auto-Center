"""Company onboarding with owner credentials; never expose provider responses to users."""
import base64
import json
import os
from datetime import datetime
from urllib import request as http
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode

from .models import FiscalApiConfig, ManagedCompany, SystemSettings, db


def management_token(config):
    return (os.getenv('FOCUS_NFE_TOKEN_PRINCIPAL') or os.getenv('FOCUSNFE_TOKEN_PRINCIPAL')
            or (config.focus_management_token if config else None))


class NoRedirect(http.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def focus_request(token, path, method='GET', payload=None):
    req = http.Request('https://api.focusnfe.com.br/v2/empresas' + path,
                       data=json.dumps(payload).encode() if payload is not None else None,
                       method=method, headers={
                           'Authorization': 'Basic ' + base64.b64encode((token + ':').encode()).decode(),
                           'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with http.build_opener(NoRedirect).open(req, timeout=30) as response:
            result = json.loads(response.read().decode())
    except HTTPError as exc:
        raise ValueError(f'A Focus não aceitou a sincronização (HTTP {exc.code}). O dono do sistema deve conferir a integração.') from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise ValueError('Não foi possível confirmar a sincronização com a Focus. Salve novamente para consultar o cadastro e tentar outra vez.') from None
    return result


def digits(value):
    return ''.join(c for c in str(value or '') if c.isascii() and c.isdigit())


def sync_company(settings, certificate=None):
    # Serialize onboarding for the single company managed by this installation.
    if settings.id:
        settings = SystemSettings.query.filter_by(id=settings.id).with_for_update().populate_existing().one()
    config = FiscalApiConfig.query.order_by(FiscalApiConfig.id).first()
    token = management_token(config)
    if not config or config.provider_name != 'FOCUSNFE' or not config.active or not token:
        raise ValueError('Cadastro salvo. A sincronização aguarda a configuração fiscal pelo dono do sistema.')
    document = digits(settings.company_document)
    document_key = 'cpf' if settings.person_type == 'FISICA' else 'cnpj'
    if len(document) != (11 if document_key == 'cpf' else 14):
        raise ValueError('Preencha o CNPJ/CPF da empresa para sincronizar o cadastro.')
    if not settings.trade_name or not settings.address or not settings.city or not settings.state:
        raise ValueError('Preencha razão social, endereço, cidade e UF para sincronizar o cadastro.')
    payload = {
        'nome': settings.trade_name, 'nome_fantasia': settings.company_name,
        document_key: document, 'logradouro': settings.address, 'numero': settings.address_number,
        'bairro': settings.neighborhood, 'complemento': settings.address_complement,
        'municipio': settings.city, 'uf': settings.state, 'cep': digits(settings.zip_code),
        'telefone': digits(settings.phone or settings.mobile), 'email': settings.email,
        'inscricao_estadual': None if settings.state_registration_exempt else digits(settings.state_registration),
        'inscricao_municipal': digits(settings.municipal_registration),
        'regime_tributario': int(settings.tax_regime) if settings.tax_regime in {'1', '2', '3', '4'} else None,
        'nome_responsavel': settings.responsible_name,
        'cpf_cnpj_contabilidade': digits(settings.accountant_cnpj or settings.accountant_cpf),
    }
    payload = {key: value for key, value in payload.items() if value not in (None, '')}
    if certificate:
        payload.update(certificate)
    # Filter on the provider, rather than trusting a manually supplied company id.
    listed = focus_request(token, '?' + urlencode({document_key: document}))
    companies = listed if isinstance(listed, list) else listed.get('empresas') if isinstance(listed, dict) else None
    if not isinstance(companies, list):
        raise ValueError('A Focus retornou uma consulta inválida. Nenhuma empresa foi criada.')
    matches = [item for item in companies if isinstance(item, dict) and digits(item.get(document_key)) == document]
    if len(matches) > 1:
        raise ValueError('Há mais de uma empresa com este documento na Focus. O dono deve conferir os cadastros.')
    existing = matches[0] if matches else None
    if existing and not existing.get('id'):
        raise ValueError('A Focus não informou o identificador do cadastro existente.')
    result = focus_request(token, '/' + quote(str(existing['id']), safe='') if existing else '',
                           'PUT' if existing else 'POST', payload)
    if not isinstance(result, dict) or not result.get('id'):
        raise ValueError('A Focus não confirmou o identificador da empresa. Salve novamente para consultar o resultado.')
    config.focus_company_id = str(result['id'])
    config.company_document = document
    config.company_name = settings.trade_name
    config.municipal_registration = settings.municipal_registration
    config.state_registration = settings.state_registration
    config.tax_regime = settings.tax_regime
    token_field = 'token_producao' if config.environment == 'PRODUCAO' else 'token_homologacao'
    if result.get(token_field):
        config.api_token = result[token_field]
    config.api_base_url = 'https://api.focusnfe.com.br' if config.environment == 'PRODUCAO' else 'https://homologacao.focusnfe.com.br'
    db.session.add(config)
    settings.focus_sync_status = 'SINCRONIZADA'
    settings.focus_synced_at = datetime.now()
    db.session.add(settings)
    return config.focus_company_id


def _parse_focus_datetime(value):
    if not value:
        return None
    candidate = str(value).replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(candidate)
        return parsed.replace(tzinfo=None)
    except ValueError:
        return None


def refresh_managed_companies():
    config = FiscalApiConfig.query.order_by(FiscalApiConfig.id).first()
    token = management_token(config)
    if not token:
        raise ValueError('Configure o token principal da Focus NFe antes de atualizar as empresas.')

    remote_companies = []
    offset = 0
    for _page in range(100):
        result = focus_request(token, '?' + urlencode({'offset': offset}))
        page = result if isinstance(result, list) else result.get('empresas', []) if isinstance(result, dict) else []
        if not isinstance(page, list):
            raise ValueError('A Focus retornou uma lista de empresas inválida.')
        remote_companies.extend(item for item in page if isinstance(item, dict))
        if len(page) < 50:
            break
        offset += 50
    else:
        raise ValueError('A consulta atingiu o limite de 5.000 empresas. Refine a integração antes de continuar.')

    seen = set()
    now = datetime.now()
    for item in remote_companies:
        focus_id = str(item.get('id') or '').strip()
        if not focus_id:
            continue
        seen.add(focus_id)
        company = ManagedCompany.query.filter_by(focus_company_id=focus_id).first() or ManagedCompany(focus_company_id=focus_id)
        address = item.get('endereco') if isinstance(item.get('endereco'), dict) else {}
        company.document = digits(item.get('cnpj') or item.get('cpf')) or None
        company.legal_name = item.get('nome') or item.get('razao_social')
        company.trade_name = item.get('nome_fantasia')
        company.email = item.get('email')
        company.phone = item.get('telefone')
        company.city = item.get('municipio') or address.get('municipio') or address.get('cidade')
        company.state = item.get('uf') or address.get('uf')
        company.remote_status = str(item.get('status') or item.get('situacao') or 'CADASTRADA').upper()
        company.certificate_expires_at = _parse_focus_datetime(item.get('data_validade_certificado') or item.get('validade_certificado'))
        company.remote_active = True
        company.last_synced_at = now
        db.session.add(company)

    for company in ManagedCompany.query.filter(ManagedCompany.remote_active.is_(True)).all():
        if company.focus_company_id not in seen:
            company.remote_active = False
            company.last_synced_at = now
    db.session.flush()
    return len(seen)
