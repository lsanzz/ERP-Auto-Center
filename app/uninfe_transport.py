"""File protocol used by the Windows UniNFe monitor.

This module never calls SEFAZ or handles private keys. Only protocol-bearing,
matching returns can advance a document to authorized.
"""
from pathlib import Path
import os
import re
import tempfile

from defusedxml import ElementTree as ET

NS = {'n': 'http://www.portalfiscal.inf.br/nfe'}
MAX_XML_BYTES = 10 * 1024 * 1024


def _read(path):
    with path.open('rb') as source:
        data = source.read(MAX_XML_BYTES + 1)
    if len(data) > MAX_XML_BYTES:
        raise ValueError('Retorno fiscal excede o limite de 10 MB.')
    return data


def _key(document):
    key = document.access_key or ''
    if not re.fullmatch(r'[0-9]{44}', key):
        raise ValueError('Documento sem chave de acesso válida para consultar o UniNFe.')
    return key


def _directory(config, field):
    raw = config.get(field, '')
    if not raw:
        raise ValueError(f'Configure a pasta do UniNFe: {field}.')
    path = Path(raw)
    if not path.is_absolute() or not path.is_dir():
        raise ValueError(f'A pasta {field} precisa existir e estar acessível por caminho absoluto.')
    return path


def apply_protocol(document, xml):
    """Apply a SEFAZ response only if its key and environment match."""
    key = _key(document)
    root = ET.fromstring(xml)
    expected_env = '1' if document.environment == 'PRODUCAO' else '2'
    protocols = root.findall('.//n:infProt', NS)
    if root.tag == '{%s}infProt' % NS['n']:
        protocols = [root]
    for protocol in protocols:
        if protocol.findtext('n:chNFe', namespaces=NS) != key:
            continue
        if protocol.findtext('n:tpAmb', namespaces=NS) != expected_env:
            raise ValueError('Ambiente do retorno UniNFe diverge do documento.')
        code = protocol.findtext('n:cStat', namespaces=NS)
        reason = protocol.findtext('n:xMotivo', namespaces=NS) or ''
        number = protocol.findtext('n:nProt', namespaces=NS)
        if code in {'100', '150'}:
            if not number:
                raise ValueError('Retorno de autorização sem protocolo.')
            # A protocol is enough to confirm authorization, but not to replace
            # the stored invoice with a receipt. Preserve the processed XML only.
            if root.tag == '{%s}nfeProc' % NS['n']:
                info = root.find('n:NFe/n:infNFe', NS)
                if info is None or info.get('Id') != 'NFe' + key:
                    raise ValueError('XML autorizado contém uma NF-e diferente do protocolo.')
                document.xml_content = xml.decode('utf-8-sig') if isinstance(xml, bytes) else xml
            if document.status not in {'CANCELADO', 'CANCELAMENTO_PENDENTE'}:
                document.status = 'AUTORIZADO'
            if document.status != 'CANCELAMENTO_PENDENTE':
                document.error_message = None
        elif code in {'110', '301', '302', '303'}:
            if document.status not in {'AUTORIZADO', 'CANCELADO'}:
                document.status = 'DENEGADO'
                document.error_message = f'{code}: {reason}'
        elif code and document.status not in {'AUTORIZADO', 'CANCELADO', 'DENEGADO'}:
            document.status = 'REJEITADO'
            document.error_message = f'{code}: {reason}'
        else:
            return False
        document.response_payload = xml.decode('utf-8-sig') if isinstance(xml, bytes) else xml
        return True
    return False


def collect_return(document, config):
    """Check immutable authorized files first, then matching individual returns."""
    key = _key(document)
    authorized = _directory(config, 'authorized_directory')
    returns = _directory(config, 'return_directory')
    situation = returns / (key + '-sit.xml')
    if situation.is_file():
        xml = _read(situation)
        root = ET.fromstring(xml)
        if (root.tag == '{%s}retConsSitNFe' % NS['n']
                and root.findtext('n:chNFe', namespaces=NS) == key):
            expected = '1' if document.environment == 'PRODUCAO' else '2'
            if root.findtext('n:tpAmb', namespaces=NS) != expected:
                raise ValueError('Ambiente da consulta diverge do documento.')
            code = root.findtext('n:cStat', namespaces=NS)
            if code in {'101', '151', '155'}:
                document.status = 'CANCELADO'
                document.response_payload = xml.decode('utf-8-sig')
                document.error_message = None
                return document
            if code == '217' and document.status not in {'AUTORIZADO', 'CANCELADO', 'DENEGADO'}:
                document.error_message = '217: NF-e não consta na base consultada. Verifique o monitor antes de reenviar.'
                document.response_payload = xml.decode('utf-8-sig')
    # UniNFe can partition authorized invoices in year/month subdirectories.
    for candidate in authorized.rglob(f'{key}-procNFe.xml'):
        if candidate.is_file() and apply_protocol(document, _read(candidate)):
            return document
    for suffix in ('-pro-rec.xml', '-sit.xml', '-den.xml'):
        candidate = returns / (key + suffix)
        if candidate.is_file() and apply_protocol(document, _read(candidate)):
            return document
    # UniNFe names receipt results by lot/receipt, not necessarily by invoice.
    lot_path = returns / (key + '-num-lot.xml')
    if lot_path.is_file():
        lot_root = ET.fromstring(_read(lot_path))
        lot = next((node.text for node in lot_root.iter()
                    if node.tag.rsplit('}', 1)[-1] == 'nLote'), None)
        if lot and re.fullmatch(r'[0-9]{1,20}', lot):
            for suffix in ('-pro-rec.xml', '-rec.xml'):
                candidate = returns / (lot + suffix)
                if candidate.is_file() and apply_protocol(document, _read(candidate)):
                    return document
    if document.status not in {'AUTORIZADO', 'CANCELADO', 'DENEGADO'}:
        for suffix in ('-nfe.err', '-rec.err', '-pro-rec.err'):
            candidate = returns / (key + suffix)
            if candidate.is_file():
                document.error_message = _read(candidate).decode('utf-8-sig', errors='replace')[:4000]
                document.status = 'ERRO'
                return document
    return document


def publish_invoice(document, config, xml):
    """Publish a prepared invoice. The caller must persist the key beforehand.

    The stable key is the monitor's duplicate identity. Retries must use exactly
    the same prepared XML, including its timestamp and numeric access-key code.
    """
    key = _key(document)
    data = xml.encode('utf-8') if isinstance(xml, str) else xml
    if len(data) > MAX_XML_BYTES:
        raise ValueError('XML fiscal excede o limite de 10 MB.')
    root = ET.fromstring(data)
    if root.tag != '{%s}NFe' % NS['n']:
        raise ValueError('O envio exige XML NF-e oficial, não o XML interno do ERP.')
    info = root.find('n:infNFe', NS)
    if info is None or info.get('Id') != 'NFe' + key or info.get('versao') != '4.00':
        raise ValueError('Chave ou versão do XML diverge da nota preparada.')
    expected_env = '1' if document.environment == 'PRODUCAO' else '2'
    if info.findtext('n:ide/n:tpAmb', namespaces=NS) != expected_env:
        raise ValueError('Ambiente do XML diverge da nota preparada.')
    model = info.findtext('n:ide/n:mod', namespaces=NS)
    if model != key[20:22] or model not in config.get('document_models', '').split(','):
        raise ValueError('Modelo de documento não habilitado para esta empresa.')
    if document.status in {'AUTORIZADO', 'CANCELADO', 'DENEGADO'}:
        raise ValueError('Documento fiscal concluído não pode ser enviado novamente.')
    target = _directory(config, 'send_directory') / (key + '-nfe.xml')
    return publish_file(target, data)


def request_situation(document, config):
    key = _key(document)
    environment = '1' if document.environment == 'PRODUCAO' else '2'
    xml = (f'<consSitNFe xmlns="{NS["n"]}" versao="4.00">'
           f'<tpAmb>{environment}</tpAmb><xServ>CONSULTAR</xServ>'
           f'<chNFe>{key}</chNFe></consSitNFe>').encode('utf-8')
    return publish_file(_directory(config, 'send_directory') / (key + '-ped-sit.xml'), xml)


def publish_file(target, data):
    if target.exists():
        if _read(target) != data:
            raise ValueError('Já existe um XML diferente com esta chave na pasta de envio.')
        return target
    # Temp extension is ignored by UniNFe. Hard-link publication is atomic and
    # cannot overwrite an existing file, unlike os.replace on POSIX.
    fd, temporary = tempfile.mkstemp(prefix='.erp-', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if _read(target) != data:
                raise ValueError('Outra emissão já publicou conteúdo diferente para esta chave.') from None
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target
