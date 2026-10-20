"""Cancellation via the UniNFe event file contract."""
from datetime import datetime
import json
import re
from zoneinfo import ZoneInfo
from xml.etree.ElementTree import Element, SubElement, tostring

from defusedxml import ElementTree as ET

from .models import FiscalDocument, UniNFeSubmission, db
from .uninfe_transport import NS, _directory, _read, publish_file
from .uninfe_xml import add


def cancellation_prefix(key):
    return '110111' + key + '01'


def build_cancellation(document, submission, justification):
    justification = (justification or '').strip()
    if not 15 <= len(justification) <= 255:
        raise ValueError('A justificativa de cancelamento deve ter entre 15 e 255 caracteres.')
    root = ET.fromstring(document.xml_content or '')
    protocol = root.find('n:protNFe/n:infProt', NS)
    if protocol is None or protocol.findtext('n:chNFe', namespaces=NS) != submission.access_key:
        raise ValueError('Recupere o XML autorizado com protocolo antes de cancelar.')
    number = protocol.findtext('n:nProt', namespaces=NS) or ''
    if not re.fullmatch(r'[0-9]{15}', number):
        raise ValueError('Protocolo de autorização inválido.')
    environment = '1' if submission.environment == 'PRODUCAO' else '2'
    if protocol.findtext('n:tpAmb', namespaces=NS) != environment:
        raise ValueError('Protocolo pertence a outro ambiente.')
    if protocol.findtext('n:cStat', namespaces=NS) not in {'100', '150'}:
        raise ValueError('O protocolo não confirma autorização.')
    envelope = Element('envEvento', xmlns=NS['n'], versao='1.00')
    add(envelope, 'idLote', str(submission.id))
    event = SubElement(envelope, 'evento', versao='1.00')
    info = SubElement(event, 'infEvento', Id='ID' + cancellation_prefix(submission.access_key))
    for tag, value in [('cOrgao', submission.access_key[:2]), ('tpAmb', environment),
        ('CNPJ', submission.issuer_document), ('chNFe', submission.access_key),
        ('dhEvento', datetime.now(ZoneInfo('America/Sao_Paulo')).isoformat(timespec='seconds')),
        ('tpEvento', '110111'), ('nSeqEvento', '1'), ('verEvento', '1.00')]:
        add(info, tag, value)
    detail = SubElement(info, 'detEvento', versao='1.00')
    add(detail, 'descEvento', 'Cancelamento')
    add(detail, 'nProt', number)
    add(detail, 'xJust', justification)
    return '<?xml version="1.0" encoding="UTF-8"?>' + tostring(envelope, encoding='unicode')


def cancel(document_id, justification):
    submission = (UniNFeSubmission.query.filter_by(document_id=document_id)
                  .with_for_update().populate_existing().one_or_none())
    document = (FiscalDocument.query.filter_by(id=document_id).with_for_update()
                .populate_existing().one_or_none())
    if not submission or not document or document.provider_name != 'UNINFE':
        raise ValueError('Reserva UniNFe não encontrada.')
    if document.status == 'CANCELADO':
        return document
    if document.status not in {'AUTORIZADO', 'CANCELAMENTO_PENDENTE'}:
        raise ValueError('Somente notas autorizadas podem ser canceladas.')
    if submission.environment != 'HOMOLOGACAO':
        raise ValueError('Cancelamento UniNFe ainda disponível apenas em homologação.')
    config = json.loads(submission.snapshot_json)['config']
    if config.get('transport') == 'remote':
        raise ValueError('Cancelamento pelo conector Windows ainda não está disponível. Não foi enviado nenhum evento.')
    target = _directory(config, 'send_directory') / (cancellation_prefix(submission.access_key) + '-ped-eve.xml')
    if submission.cancellation_xml:
        db.session.commit()
        collect_cancellation(document, submission)
        return document
    xml = build_cancellation(document, submission, justification)
    submission.cancellation_xml = xml
    document.status = 'CANCELAMENTO_PENDENTE'
    db.session.commit()
    publish_file(target, xml.encode('utf-8'))
    return document


def collect_cancellation(document, submission):
    if not submission.cancellation_xml:
        return False
    config = json.loads(submission.snapshot_json)['config']
    prefix = cancellation_prefix(submission.access_key)
    authorized = _directory(config, 'authorized_directory')
    for processed_path in authorized.rglob('*' + submission.access_key + '*-procEventoNFe.xml'):
        xml = _read(processed_path)
        root = ET.fromstring(xml)
        if root.tag != '{%s}procEventoNFe' % NS['n']:
            continue
        request = root.find('n:evento/n:infEvento', NS)
        if request is None or request.get('Id') != 'ID' + prefix:
            continue
        if apply_cancellation_response(document, submission, xml) and document.status == 'CANCELADO':
            submission.cancellation_processed_xml = xml.decode('utf-8-sig')
            return True
    target = _directory(config, 'return_directory') / (prefix + '-eve.xml')
    if not target.is_file():
        return False
    xml = _read(target)
    return apply_cancellation_response(document, submission, xml)


def apply_cancellation_response(document, submission, xml):
    root = ET.fromstring(xml)
    events = root.findall('.//n:retEvento/n:infEvento', NS)
    if root.tag == '{%s}retEvento' % NS['n']:
        events = root.findall('n:infEvento', NS)
    for event in events:
        get = lambda tag: event.findtext('n:' + tag, namespaces=NS)
        if get('chNFe') != submission.access_key or get('tpEvento') != '110111' or get('nSeqEvento') != '1':
            continue
        if get('tpAmb') != ('1' if submission.environment == 'PRODUCAO' else '2'):
            raise ValueError('Ambiente do evento diverge da nota.')
        code = get('cStat')
        if code in {'135', '155'}:
            if not get('nProt'):
                raise ValueError('Retorno do cancelamento não possui protocolo.')
            document.status = 'CANCELADO'
            document.error_message = None
        else:
            document.error_message = f'Cancelamento: {code} — {get("xMotivo") or "verifique o retorno"}'
        submission.cancellation_response = xml.decode('utf-8-sig')
        return True
    return False
