from datetime import datetime
from decimal import Decimal
from defusedxml import ElementTree as ET
from .utils import parse_decimal

NS = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}

FORMAS_PAGAMENTO_MAP = {
    '01': 'Dinheiro',
    '02': 'Cheque',
    '03': 'Cartão de Crédito',
    '04': 'Cartão de Débito',
    '05': 'Crédito Loja',
    '10': 'Vale Alimentação',
    '11': 'Vale Refeição',
    '12': 'Vale Presente',
    '13': 'Vale Combustível',
    '14': 'Duplicata Mercantil',
    '15': 'Boleto',
    '16': 'Depósito Bancário',
    '17': 'PIX',
    '18': 'Transferência Bancária',
    '19': 'Programa de Fidelidade',
    '90': 'Sem Pagamento',
    '99': 'Outros',
}

def _text(node, path: str, default=None):
    found = node.find(path, NS) if node is not None else None
    return found.text.strip() if found is not None and found.text is not None else default


def _deep_text(node, names: set[str], default=None):
    if node is None:
        return default
    for child in node.iter():
        tag = child.tag.rsplit('}', 1)[-1]
        if tag in names and child.text and child.text.strip():
            return child.text.strip()
    return default


def _number(value):
    return float(parse_decimal(value or '0'))


def _format_cnpj_cpf(val: str | None) -> str:
    if not val:
        return ''
    digits = ''.join(ch for ch in str(val) if ch.isdigit())
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    elif len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    return val


def _format_datetime(iso_str: str | None) -> str:
    if not iso_str:
        return ''
    try:
        clean = iso_str.replace('Z', '+00:00')
        dt = datetime.fromisoformat(clean)
        return dt.strftime('%d/%m/%Y %H:%M')
    except Exception:
        return iso_str


def _format_date(date_str: str | None) -> str:
    if not date_str:
        return ''
    try:
        if 'T' in date_str:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00')).strftime('%d/%m/%Y')
        parts = date_str.split('-')
        if len(parts) == 3:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
    except ValueError:
        return date_str
    return date_str


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

    dh_emi_raw = _text(ide, 'nfe:dhEmi')
    issue_date = None
    if dh_emi_raw:
        try:
            issue_date = datetime.fromisoformat(dh_emi_raw.replace('Z', '+00:00')).date()
        except ValueError:
            issue_date = None

    dh_recbto_raw = _text(prot, 'nfe:dhRecbto')
    dh_recbto_fmt = _format_datetime(dh_recbto_raw)
    dh_emi_fmt = _format_datetime(dh_emi_raw)

    versao_aplicativo = _text(ide, 'nfe:verProc') or _text(prot, 'nfe:verAplic') or '-'
    if versao_aplicativo:
        versao_aplicativo = versao_aplicativo.upper()

    items = []
    for det in inf.findall('nfe:det', NS):
        prod = det.find('nfe:prod', NS)
        if prod is None:
            continue
            
        qty = parse_decimal(_text(prod, 'nfe:qCom', '0'))
        unit_value = parse_decimal(_text(prod, 'nfe:vUnCom', '0'))
        total_value = parse_decimal(_text(prod, 'nfe:vProd', '0'))
        
        imposto = det.find('nfe:imposto', NS)
        items.append({
            'numero_item': det.attrib.get('nItem'),
            'codigo': _text(prod, 'nfe:cProd'),
            'descricao': _text(prod, 'nfe:xProd'),
            'ncm': _text(prod, 'nfe:NCM', '-'),
            'cfop': _text(prod, 'nfe:CFOP', '-'),
            'unidade': _text(prod, 'nfe:uCom', 'UN'),
            'quantidade': float(qty),
            'valor_unitario': float(unit_value),
            'valor_total': float(total_value),
            'unidade_tributavel': _text(prod, 'nfe:uTrib', _text(prod, 'nfe:uCom', 'UN')),
            'quantidade_tributavel': _number(_text(prod, 'nfe:qTrib', _text(prod, 'nfe:qCom', '0'))),
            'valor_unitario_tributavel': _number(_text(prod, 'nfe:vUnTrib', _text(prod, 'nfe:vUnCom', '0'))),
            'desconto': _number(_text(prod, 'nfe:vDesc', '0')),
            'frete': _number(_text(prod, 'nfe:vFrete', '0')),
            'seguro': _number(_text(prod, 'nfe:vSeg', '0')),
            'outras_despesas': _number(_text(prod, 'nfe:vOutro', '0')),
            'ean': _text(prod, 'nfe:cEAN'),
            'ean_tributavel': _text(prod, 'nfe:cEANTrib'),
            'icms_origem': _deep_text(imposto, {'orig'}),
            'icms_cst': _deep_text(imposto, {'CST', 'CSOSN'}),
            'icms_base': _number(_deep_text(imposto, {'vBC'})),
            'icms_aliquota': _number(_deep_text(imposto, {'pICMS'})),
            'icms_valor': _number(_deep_text(imposto, {'vICMS'})),
            'ipi_cst': _deep_text(imposto, {'CST'}),
            'ipi_valor': _number(_deep_text(imposto, {'vIPI'})),
            'pis_valor': _number(_deep_text(imposto, {'vPIS'})),
            'cofins_valor': _number(_deep_text(imposto, {'vCOFINS'})),
        })

    faturas = []
    for dup in inf.findall('.//nfe:cobr/nfe:dup', NS):
        venc_raw = _text(dup, 'nfe:dVenc', '')
        faturas.append({
            'numero': _text(dup, 'nfe:nDup', '-'),
            'vencimento': venc_raw,
            'vencimento_fmt': _format_date(venc_raw),
            'valor': float(parse_decimal(_text(dup, 'nfe:vDup', '0')))
        })

    transp = inf.find('nfe:transp', NS)
    transporta = transp.find('nfe:transporta', NS) if transp is not None else None
    vol = transp.find('nfe:vol', NS) if transp is not None else None
    
    mod_frete = _text(transp, 'nfe:modFrete', '9')
    transportadora_nome = _text(transporta, 'nfe:xNome')
    if transportadora_nome:
        transportador_display = transportadora_nome
    elif mod_frete == '9':
        transportador_display = 'SEM FRETE'
    else:
        transportador_display = f"Modalidade {mod_frete}"

    peso_b = _text(vol, 'nfe:pesoB')
    peso_l = _text(vol, 'nfe:pesoL')
    if peso_b or peso_l:
        try:
            pb_num = float(parse_decimal(peso_b or '0'))
            pl_num = float(parse_decimal(peso_l or '0'))
            peso_bruto_liquido = f"{pb_num:.2f} - {pl_num:.2f}".replace('.', ',')
        except Exception:
            peso_bruto_liquido = f"{peso_b or '0'} - {peso_l or '0'}"
    else:
        peso_bruto_liquido = '0,00 - 0,00'

    pag = inf.find('nfe:pag', NS)
    pagamentos = []
    forma_pagamento_sugerida = 'Boleto'
    if pag is not None:
        for det_pag in pag.findall('nfe:detPag', NS):
            meio = _text(det_pag, 'nfe:tPag')
            descricao_meio = FORMAS_PAGAMENTO_MAP.get(meio, _text(det_pag, 'nfe:xPag', 'Outros'))
            if meio:
                forma_pagamento_sugerida = FORMAS_PAGAMENTO_MAP.get(meio, 'Boleto')
            pagamentos.append({
                'meio': meio,
                'descricao_meio': descricao_meio,
                'valor': _number(_text(det_pag, 'nfe:vPag', '0')),
                'troco': _number(_text(pag, 'nfe:vTroco', '0')),
            })

    totais = {
        'base_icms': _number(_text(total, 'nfe:vBC', '0')),
        'valor_icms': _number(_text(total, 'nfe:vICMS', '0')),
        'base_icms_st': _number(_text(total, 'nfe:vBCST', '0')),
        'valor_icms_st': _number(_text(total, 'nfe:vST', '0')),
        'valor_produtos': _number(_text(total, 'nfe:vProd', '0')),
        'valor_frete': _number(_text(total, 'nfe:vFrete', '0')),
        'valor_seguro': _number(_text(total, 'nfe:vSeg', '0')),
        'valor_desconto': _number(_text(total, 'nfe:vDesc', '0')),
        'valor_ii': _number(_text(total, 'nfe:vII', '0')),
        'valor_ipi': _number(_text(total, 'nfe:vIPI', '0')),
        'valor_pis': _number(_text(total, 'nfe:vPIS', '0')),
        'valor_cofins': _number(_text(total, 'nfe:vCOFINS', '0')),
        'valor_outras_despesas': _number(_text(total, 'nfe:vOutro', '0')),
        'valor_nota': _number(_text(total, 'nfe:vNF', '0')),
    }

    emit_cnpj_raw = _text(emit, 'nfe:CNPJ') or _text(emit, 'nfe:CPF')
    emit_cnpj_fmt = _format_cnpj_cpf(emit_cnpj_raw)

    c_stat = _text(prot, 'nfe:cStat')
    x_motivo = _text(prot, 'nfe:xMotivo')
    if c_stat and x_motivo:
        status_completo = f"{c_stat} - {x_motivo}"
    else:
        status_completo = x_motivo or 'Autorizado o uso da NF-e'

    return {
        'chave_acesso': _text(prot, 'nfe:chNFe') or (inf.attrib.get('Id') or '').replace('NFe', ''),
        'numero': _text(ide, 'nfe:nNF'),
        'serie': _text(ide, 'nfe:serie'),
        'natureza_operacao': _text(ide, 'nfe:natOp'),
        'issued_at': issue_date.isoformat() if issue_date else None,
        'dh_emi_formatado': dh_emi_fmt,
        'dh_recbto_formatado': dh_recbto_fmt,
        'versao_aplicativo': versao_aplicativo,
        'emitente_nome': _text(emit, 'nfe:xNome'),
        'emitente_fantasia': _text(emit, 'nfe:xFant', ''),
        'emitente_cnpj': emit_cnpj_raw,
        'emitente_cnpj_formatado': emit_cnpj_fmt,
        'emitente_ie': _text(emit, 'nfe:IE', '-'),
        'emitente_endereco': _text(emit, 'nfe:enderEmit/nfe:xLgr', '') + (', ' + _text(emit, 'nfe:enderEmit/nfe:nro', '') if _text(emit, 'nfe:enderEmit/nfe:nro') else ''),
        'emitente_bairro': _text(emit, 'nfe:enderEmit/nfe:xBairro', ''),
        'emitente_cidade': _text(emit, 'nfe:enderEmit/nfe:xMun', '') + ('/ ' + _text(emit, 'nfe:enderEmit/nfe:UF', '') if _text(emit, 'nfe:enderEmit/nfe:UF') else ''),
        'emitente_cep': _text(emit, 'nfe:enderEmit/nfe:CEP', ''),
        'emitente_telefone': _text(emit, 'nfe:enderEmit/nfe:fone', ''),
        'destinatario_nome': _text(dest, 'nfe:xNome'),
        'destinatario_cnpj': _text(dest, 'nfe:CNPJ') or _text(dest, 'nfe:CPF'),
        'destinatario_ie': _text(dest, 'nfe:IE', '-'),
        'destinatario_endereco': _text(dest, 'nfe:enderDest/nfe:xLgr', '') + (', ' + _text(dest, 'nfe:enderDest/nfe:nro', '') if _text(dest, 'nfe:enderDest/nfe:nro') else ''),
        'destinatario_bairro': _text(dest, 'nfe:enderDest/nfe:xBairro', ''),
        'destinatario_cidade': _text(dest, 'nfe:enderDest/nfe:xMun', '') + ('/ ' + _text(dest, 'nfe:enderDest/nfe:UF', '') if _text(dest, 'nfe:enderDest/nfe:UF') else ''),
        'destinatario_cep': _text(dest, 'nfe:enderDest/nfe:CEP', ''),
        'destinatario_telefone': _text(dest, 'nfe:enderDest/nfe:fone', ''),
        'finalidade_emissao': _text(ide, 'nfe:finNFe'),
        'tipo_documento': _text(ide, 'nfe:tpNF'),
        'local_destino': _text(ide, 'nfe:idDest'),
        'presenca_comprador': _text(ide, 'nfe:indPres'),
        'total_produtos': totais['valor_produtos'],
        'total_frete': totais['valor_frete'],
        'total_desconto': totais['valor_desconto'],
        'total_ipi': totais['valor_ipi'],
        'total_nota': totais['valor_nota'],
        'totais': totais,
        'peso_bruto_liquido': peso_bruto_liquido,
        'transportador_descricao': transportador_display,
        'forma_pagamento_sugerida': forma_pagamento_sugerida,
        'status': _text(prot, 'nfe:xMotivo'),
        'status_completo': status_completo,
        'protocolo': _text(prot, 'nfe:nProt'),
        'itens': items,
        'faturas': faturas,
        'pagamentos': pagamentos,
        'transporte': {
            'modalidade_frete': mod_frete,
            'transportadora': transportadora_nome,
            'cnpj_transportadora': _text(transporta, 'nfe:CNPJ'),
            'cpf_transportadora': _text(transporta, 'nfe:CPF'),
            'placa': _text(transporta, 'nfe:placa'),
            'uf': _text(transporta, 'nfe:UF'),
            'rntrc': _text(transporta, 'nfe:RNTC'),
            'quantidade_volumes': _text(vol, 'nfe:qVol'),
            'especie': _text(vol, 'nfe:esp'),
            'marca': _text(vol, 'nfe:marca'),
            'numeracao': _text(vol, 'nfe:nVol'),
            'peso_bruto': peso_b,
            'peso_liquido': peso_l,
        },
        'identificacao': {
            'modelo': _text(ide, 'nfe:mod'),
            'versao_processo': _text(prot, 'nfe:verAplic'),
            'ambiente': _text(prot, 'nfe:tpAmb'),
            'protocolo': _text(prot, 'nfe:nProt'),
            'digest_value': _text(prot, 'nfe:digVal'),
        },
        'informacoes_complementares': _text(inf.find('nfe:infAdic', NS), 'nfe:infCpl'),
    }
