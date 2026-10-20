"""Company-owned UniNFe configuration; private keys stay in the fiscal monitor."""
import json
import re
from decimal import Decimal, InvalidOperation

from .models import FiscalApiConfig, db


def get_config(settings):
    return json.loads(settings.uninfe_settings_json or '{}')


def reconcile_company_config(settings, *, previous_city):
    """Validate company edits and invalidate an IBGE code from a former city/UF.

    Company and monitor settings are separate forms. Keeping the former code
    would silently combine two addresses; rejecting the UF change would prevent
    changing either form first. Clear only the incompatible code instead.
    Returns True when the municipality needs to be selected again.
    """
    config = get_config(settings)
    if not config:
        return False
    from .uninfe_preparation import UF_CODES
    if settings.state not in UF_CODES:
        raise ValueError('Selecione uma UF válida no cadastro da empresa.')
    if settings.tax_regime not in {'1', '2', '3', '4'}:
        raise ValueError('Selecione um regime tributário válido no cadastro da empresa.')
    city_code = config.get('city_code', '')
    normalized_city = lambda value: ' '.join((value or '').split()).casefold()
    city_changed = normalized_city(previous_city) != normalized_city(settings.city)
    if city_code and (city_changed or not city_code.startswith(UF_CODES[settings.state])):
        config['city_code'] = ''
        settings.uninfe_settings_json = json.dumps(config, ensure_ascii=False)
        return True
    return False


def save_config(settings, form):
    values = {}
    choices = {
        'environment': {'HOMOLOGACAO', 'PRODUCAO'},
        'certificate_type': {'A1', 'A3'},
        'document_models': {'55', '55,65'},
    }
    for field, options in choices.items():
        value = form.get(field, '').strip()
        if value not in options:
            raise ValueError(f'Opção inválida: {field}.')
        values[field] = value
    city_code = form.get('city_code', '').strip()
    if not re.fullmatch(r'[0-9]{7}', city_code):
        raise ValueError('Informe o código IBGE do município com 7 dígitos.')
    from .uninfe_preparation import UF_CODES
    if settings.state and (settings.state not in UF_CODES or not city_code.startswith(UF_CODES[settings.state])):
        raise ValueError('O código IBGE informado não corresponde à UF da empresa.')
    if settings.tax_regime and settings.tax_regime not in {'1', '2', '3', '4'}:
        raise ValueError('Selecione um regime tributário válido no cadastro da empresa.')
    values['city_code'] = city_code
    origin = form.get('origin', '').strip()
    if origin and origin not in set('012345678'):
        raise ValueError('Origem da mercadoria inválida.')
    values['origin'] = origin
    for field in ('send_directory', 'return_directory', 'authorized_directory',
                  'error_directory', 'certificate_reference', 'accountant_rules'):
        value = form.get(field, '').strip()
        if len(value) > (20000 if field == 'accountant_rules' else 1000):
            raise ValueError(f'Campo muito longo: {field}.')
        if '\x00' in value:
            raise ValueError('Caractere inválido nas configurações.')
        values[field] = value
    for field in ('nfe_series', 'nfce_series'):
        raw = form.get(field, '').strip()
        if not raw.isascii() or not raw.isdigit() or not 0 <= int(raw) <= 999:
            raise ValueError('A série deve ser um número entre 0 e 999.')
        values[field] = int(raw)
    for field in ('nfe_next_number', 'nfce_next_number'):
        raw = form.get(field, '').strip()
        if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 999999999:
            raise ValueError('A próxima numeração deve estar entre 1 e 999999999.')
        values[field] = int(raw)
    for field, pattern in {'cfop_internal': r'5\d{3}', 'cfop_interstate': r'6\d{3}',
                           'csosn': r'\d{3}', 'icms_cst': r'\d{2}',
                           'pis_cst': r'\d{2}', 'cofins_cst': r'\d{2}'}.items():
        value = form.get(field, '').strip()
        if value and not re.fullmatch(pattern, value):
            raise ValueError(f'Código inválido: {field}.')
        values[field] = value
    for field in ('icms_rate', 'pis_rate', 'cofins_rate', 'credit_rate'):
        value = form.get(field, '').strip().replace(',', '.')
        if value:
            try:
                amount = Decimal(value)
                if not amount.is_finite() or not 0 <= amount <= 100:
                    raise InvalidOperation
            except InvalidOperation:
                raise ValueError('As alíquotas devem estar entre 0 e 100%.') from None
            value = str(amount)
        values[field] = value
    # Build and validate everything before changing persistent state.
    settings.uninfe_settings_json = json.dumps(values, ensure_ascii=False)
    db.session.add(settings)
    config = FiscalApiConfig.query.order_by(FiscalApiConfig.id).first()
    if config is None:
        config = FiscalApiConfig()
    config.provider_name = 'UNINFE'
    config.api_token = None
    config.api_base_url = None
    config.focus_management_token = None
    config.environment = values['environment']
    config.active = True
    config.company_name = settings.trade_name or settings.company_name
    config.company_document = settings.company_document
    config.tax_regime = settings.tax_regime
    config.state_registration = settings.state_registration
    config.municipal_registration = settings.municipal_registration
    db.session.add(config)
    return values
