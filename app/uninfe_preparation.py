"""Transactional reservation of NF-e identities before any monitor file I/O."""
from datetime import datetime
import hashlib
import json
import re
import secrets
from zoneinfo import ZoneInfo
from flask import current_app

from .models import FiscalDocument, SystemSettings, UniNFeSubmission, db
from .uninfe_config import get_config

UF_CODES = dict(RO='11', AC='12', AM='13', RR='14', PA='15', AP='16', TO='17',
                MA='21', PI='22', CE='23', RN='24', PB='25', PE='26', AL='27',
                SE='28', BA='29', MG='31', ES='32', RJ='33', SP='35', PR='41',
                SC='42', RS='43', MS='50', MT='51', GO='52', DF='53')


def access_key(uf, issued_at, cnpj, model, series, number, numeric_code):
    if uf not in UF_CODES or not re.fullmatch(r'[0-9]{14}', cnpj):
        raise ValueError('Informe CNPJ e UF válidos no cadastro da empresa.')
    if model not in {'55', '65'} or not 0 <= series <= 999 or not 1 <= number <= 999999999:
        raise ValueError('Modelo, série ou número fiscal inválido.')
    if not re.fullmatch(r'[0-9]{8}', numeric_code):
        raise ValueError('Código numérico inválido.')
    base = f'{UF_CODES[uf]}{issued_at:%y%m}{cnpj}{model}{series:03d}{number:09d}1{numeric_code}'
    total = sum(int(digit) * (2 + index % 8) for index, digit in enumerate(reversed(base)))
    digit = 11 - total % 11
    return base + str(0 if digit >= 10 else digit)


def prepare(document_id, builder):
    """Reserve and build in one transaction; caller must commit before publish.

    The builder receives (payload, company snapshot, monitor config, identity).
    It must fully validate/generate the invoice without external side effects.
    All reservations serialize on the company settings row in MySQL; database
    uniqueness also protects against conflicting series/number resets.
    """
    settings = (SystemSettings.query.order_by(SystemSettings.id).with_for_update()
                .populate_existing().first())
    if settings is None:
        raise ValueError('Cadastre a empresa antes de emitir.')
    document = (FiscalDocument.query.filter_by(id=document_id).with_for_update()
                .populate_existing().first())
    if document is None or document.provider_name != 'UNINFE':
        raise ValueError('Documento não pertence ao UniNFe.')
    existing = UniNFeSubmission.query.filter_by(document_id=document_id).first()
    if existing:
        return existing
    if document.status not in {'RASCUNHO', 'PRONTO_PARA_ENVIO', 'NA_FILA', 'ERRO'}:
        raise ValueError('O estado da nota não permite reservar uma nova emissão.')
    config = get_config(settings)
    config['transport'] = current_app.config.get('UNINFE_TRANSPORT', 'local')
    if config['transport'] not in {'local', 'remote'}:
        raise ValueError('Transporte UniNFe inválido na configuração da instalação.')
    model = {'NFE': '55', 'NFCE': '65'}.get(document.document_type)
    if not model or model not in config.get('document_models', '').split(','):
        raise ValueError('Modelo fiscal não habilitado para esta empresa.')
    if document.environment != config.get('environment'):
        raise ValueError('O ambiente da nota diverge das configurações da empresa.')
    cnpj = re.sub(r'[^0-9]', '', settings.company_document or '')
    prefix = 'nfe' if model == '55' else 'nfce'
    series, number = config[prefix + '_series'], config[prefix + '_next_number']
    # A saved form may be stale, or the user may return to an old series. Never
    # recycle a number that has already been durably reserved in this scope.
    last = db.session.query(db.func.max(UniNFeSubmission.number)).filter_by(
        issuer_document=cnpj, environment=document.environment, model=model, series=series).scalar()
    number = max(number, (last or 0) + 1)
    now = datetime.now(ZoneInfo('America/Sao_Paulo'))
    key = access_key(settings.state, now, cnpj, model, series, number, f'{secrets.randbelow(100000000):08d}')
    identity = dict(key=key, model=model, series=series, number=number,
                    issued_at=now.isoformat(timespec='seconds'), environment=document.environment)
    # Explicit public fiscal fields: never snapshot account or certificate secrets.
    company = {field: getattr(settings, field) for field in (
        'company_name', 'trade_name', 'company_document', 'tax_regime',
        'state_registration', 'state_registration_exempt', 'municipal_registration',
        'address', 'address_number', 'neighborhood', 'address_complement',
        'city', 'state', 'zip_code', 'phone')}
    payload = json.loads(document.request_payload or '{}')
    xml = builder(payload, company, config.copy(), identity.copy())
    if not isinstance(xml, str) or not xml.strip():
        raise ValueError('O gerador não produziu um XML fiscal.')
    submission = UniNFeSubmission(document_id=document.id, issuer_document=cnpj,
        environment=document.environment, model=model, series=series, number=number,
        access_key=key, issued_at=identity['issued_at'], prepared_xml=xml,
        xml_sha256=hashlib.sha256(xml.encode('utf-8')).hexdigest(),
        snapshot_json=json.dumps(dict(payload=payload, company=company, config=config,
                                      identity=identity), ensure_ascii=False))
    config[prefix + '_next_number'] = number + 1
    settings.uninfe_settings_json = json.dumps(config, ensure_ascii=False)
    document.access_key = key
    document.numero = str(number)
    document.serie = str(series)
    document.xml_content = xml
    document.status = 'PREPARADO'
    db.session.add(submission)
    db.session.flush()
    return submission
