from datetime import datetime
from decimal import Decimal
from xml.etree import ElementTree as ET
from .utils import parse_decimal

NS = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}

def _text(node, path: str, default=None):
    found = node.find(path, NS) if node is not None else None
    return found.text.strip() if found is not None and found.text is not None else default

def parse_nfe_xml(xml_bytes: bytes) -> dict:
    root = ET.fromstring(xml_bytes)
    inf = root.find('.//nfe:infNFe', NS)
    if inf is None:
        raise ValueError('XML de NF-e inválido.')

    ide = inf.find('nfe:ide', NS)
    emit = inf.find('nfe:emit', NS)
    dest = inf.find('nfe:dest', NS)
    total = inf.find('nfe:total/nfe:ICMSTot', NS)
    prot = root.find('.//nfe:protNFe/nfe:infProt', NS)

    dh_emi = _text(ide, 'nfe:dhEmi')
    issue_date = None
    if dh_emi:
        issue_date = datetime.fromisoformat(dh_emi.replace('Z', '+00:00')).date()

    items = []
    for det in inf.findall('nfe:det', NS):
        prod = det.find('nfe:prod', NS)
        if prod is None:
            continue
            
        qty = parse_decimal(_text(prod, 'nfe:qCom', '0'))
        unit_value = parse_decimal(_text(prod, 'nfe:vUnCom', '0'))
        total_value = parse_decimal(_text(prod, 'nfe:vProd', '0'))
        
        items.append({
            'codigo': _text(prod, 'nfe:cProd'),
            'descricao': _text(prod, 'nfe:xProd'),
            'ncm': _text(prod, 'nfe:NCM', '-'),
            'cfop': _text(prod, 'nfe:CFOP', '-'),
            'unidade': _text(prod, 'nfe:uCom', 'UN'),
            'quantidade': float(qty),
            'valor_unitario': float(unit_value),
            'valor_total': float(total_value),
        })

    faturas = []
    for dup in inf.findall('.//nfe:cobr/nfe:dup', NS):
        faturas.append({
            'numero': _text(dup, 'nfe:nDup', '-'),
            'vencimento': _text(dup, 'nfe:dVenc', ''),
            'valor': float(parse_decimal(_text(dup, 'nfe:vDup', '0')))
        })

    return {
        'chave_acesso': _text(prot, 'nfe:chNFe') or (inf.attrib.get('Id') or '').replace('NFe', ''),
        'numero': _text(ide, 'nfe:nNF'),
        'serie': _text(ide, 'nfe:serie'),
        'natureza_operacao': _text(ide, 'nfe:natOp'),
        'issued_at': issue_date.isoformat() if issue_date else None,
        'emitente_nome': _text(emit, 'nfe:xNome'),
        'emitente_fantasia': _text(emit, 'nfe:xFant', _text(emit, 'nfe:xNome')),
        'emitente_cnpj': _text(emit, 'nfe:CNPJ'),
        'emitente_ie': _text(emit, 'nfe:IE', '-'),
        'emitente_endereco': _text(emit, 'nfe:enderEmit/nfe:xLgr', '') + ', ' + _text(emit, 'nfe:enderEmit/nfe:nro', ''),
        'emitente_bairro': _text(emit, 'nfe:enderEmit/nfe:xBairro', ''),
        'emitente_cidade': _text(emit, 'nfe:enderEmit/nfe:xMun', '') + '/' + _text(emit, 'nfe:enderEmit/nfe:UF', ''),
        'emitente_cep': _text(emit, 'nfe:enderEmit/nfe:CEP', ''),
        'emitente_telefone': _text(emit, 'nfe:enderEmit/nfe:fone', ''),
        'destinatario_nome': _text(dest, 'nfe:xNome'),
        'destinatario_cnpj': _text(dest, 'nfe:CNPJ') or _text(dest, 'nfe:CPF'),
        'total_produtos': float(parse_decimal(_text(total, 'nfe:vProd', '0'))),
        'total_frete': float(parse_decimal(_text(total, 'nfe:vFrete', '0'))),
        'total_desconto': float(parse_decimal(_text(total, 'nfe:vDesc', '0'))),
        'total_ipi': float(parse_decimal(_text(total, 'nfe:vIPI', '0'))),
        'total_nota': float(parse_decimal(_text(total, 'nfe:vNF', '0'))),
        'status': _text(prot, 'nfe:xMotivo'),
        'itens': items,
        'faturas': faturas,
        'informacoes_complementares': _text(inf.find('nfe:infAdic', NS), 'nfe:infCpl'),
    }