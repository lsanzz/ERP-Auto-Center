"""NF-e 4.00 XML construction from explicit fiscal data.

Unsigned documents are signed by UniNFe. No address or tax classification is
inferred from free text. Unsupported tax situations fail before reservation.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from xml.etree.ElementTree import Element, SubElement, tostring

from .uninfe_preparation import UF_CODES

NAMESPACE = 'http://www.portalfiscal.inf.br/nfe'


def add(parent, name, value):
    node = SubElement(parent, name)
    node.text = str(value)
    return node


def required(value, label):
    value = str(value or '').strip()
    if not value:
        raise ValueError(f'Preencha {label} antes de emitir.')
    return value


def digits(value, length, label):
    value = re.sub(r'[. /()-]', '', str(value or ''))
    if not re.fullmatch(r'[0-9]{%d}' % length, value):
        raise ValueError(f'{label} deve conter {length} dígitos.')
    return value


def decimal(value, label, default=None):
    if value in (None, ''):
        if default is None:
            raise ValueError(f'Informe {label}.')
        value = default
    try:
        result = Decimal(str(value).replace(',', '.'))
        if not result.is_finite() or result < 0:
            raise InvalidOperation
        return result
    except InvalidOperation:
        raise ValueError(f'Valor inválido para {label}.') from None


def money(value):
    return format(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP), '.2f')


def allocate(total, weights):
    """Distribute exact cents by largest remainder, preserving the invoice sum."""
    cents = int(Decimal(money(total)) * 100)
    denominator = sum(weights)
    if denominator <= 0:
        if cents:
            raise ValueError('Não é possível ratear valores em itens sem valor líquido.')
        return [Decimal('0')] * len(weights)
    exact = [Decimal(cents) * weight / denominator for weight in weights]
    shares = [int(value) for value in exact]
    remaining = cents - sum(shares)
    order = sorted(range(len(weights)), key=lambda index: (exact[index] - shares[index], -index), reverse=True)
    for index in order[:remaining]:
        shares[index] += 1
    return [Decimal(value) / 100 for value in shares]


def address(parent, data, label):
    for tag, field in [('xLgr', 'address'), ('nro', 'address_number')]:
        add(parent, tag, required(data.get(field), f'{label}: {field}'))
    if data.get('address_complement'):
        add(parent, 'xCpl', data['address_complement'])
    add(parent, 'xBairro', required(data.get('neighborhood'), f'bairro de {label}'))
    city_code = digits(data.get('city_code'), 7, f'Código IBGE de {label}')
    state = required(data.get('state'), f'UF de {label}').upper()
    if state not in UF_CODES or not city_code.startswith(UF_CODES[state]):
        raise ValueError(f'Código IBGE e UF de {label} não correspondem.')
    add(parent, 'cMun', city_code)
    add(parent, 'xMun', required(data.get('city'), f'município de {label}'))
    add(parent, 'UF', state)
    add(parent, 'CEP', digits(data.get('zip_code'), 8, f'CEP de {label}'))
    add(parent, 'cPais', '1058')
    add(parent, 'xPais', 'BRASIL')


def contribution(parent, name, code, rate, base):
    code = required(code, f'CST {name}')
    group = SubElement(parent, name)
    if code in {'04', '05', '06', '07', '08', '09'}:
        add(SubElement(group, name + 'NT'), 'CST', code)
        return Decimal('0')
    if code not in {'01', '02'}:
        raise ValueError(f'CST {name} {code} ainda precisa de implementação tributária específica.')
    rate = decimal(rate, f'alíquota {name}')
    if rate > 100:
        raise ValueError(f'Alíquota de {name} superior a 100%.')
    amount = Decimal(money(base * rate / 100))
    detail = SubElement(group, name + 'Aliq')
    add(detail, 'CST', code)
    add(detail, 'vBC', money(base))
    add(detail, 'p' + name, format(rate, '.4f'))
    add(detail, 'v' + name, money(amount))
    return amount


def retained_icms(group, item):
    """Prior-operation amounts supplied by the accountant, never recomputed."""
    fields = ('vBCSTRet', 'pST', 'vICMSSubstituto', 'vICMSSTRet')
    if any(item.get(field) not in (None, '') for field in fields):
        for field in fields:
            if field == 'vICMSSubstituto' and item.get(field) in (None, ''):
                continue
            value = decimal(item.get(field), field)
            if field == 'pST' and value > 100:
                raise ValueError('Alíquota ST superior a 100%.')
            add(group, field, format(value, '.4f') if field == 'pST' else money(value))


def build_invoice(payload, company, config, identity):
    model = identity['model']
    if model not in {'55', '65'}:
        raise ValueError('Modelo fiscal inválido.')
    invoice = payload.get('invoice') or {}
    # Until allocation/transport support is implemented, never silently omit
    # monetary data that the existing invoice form already allows entering.
    for field in ('valor_icms_st', 'valor_ipi', 'percentual_desconto'):
        if decimal(invoice.get(field), field, 0):
            raise ValueError(f'{field} ainda precisa de integração ao cálculo fiscal do UniNFe.')
    if str(invoice.get('tipo_documento') or '1') != '1':
        raise ValueError('Entrada de mercadoria precisa de tratamento fiscal específico.')
    customer = payload.get('customer') or {}
    items = payload.get('items', {}).get('parts') or []
    if not items or payload.get('items', {}).get('services'):
        raise ValueError('Informe os produtos da NF-e/NFC-e; serviços devem usar NFS-e.')
    company = company | {'city_code': config.get('city_code')}
    crt = required(company.get('tax_regime'), 'regime tributário')
    if crt not in {'1', '2', '3', '4'}:
        raise ValueError('Regime tributário inválido.')
    root = Element('NFe', xmlns=NAMESPACE)
    info = SubElement(root, 'infNFe', Id='NFe' + identity['key'], versao='4.00')
    ide = SubElement(info, 'ide')
    destination = required(customer.get('state'), 'UF do destinatário')
    dest_code = '1' if destination == company.get('state') else '2'
    if model == '65':
        if dest_code != '1' or invoice.get('consumidor_final') != '1':
            raise ValueError('NFC-e exige operação interna para consumidor final.')
        if str(invoice.get('finalidade_emissao') or '1') != '1':
            raise ValueError('NFC-e exige finalidade normal.')
        if str(invoice.get('tipo_atendimento') or '0') not in {'1', '4'}:
            raise ValueError('Informe atendimento presencial ou entrega em domicílio para NFC-e.')
    for tag, value in [('cUF', identity['key'][:2]), ('cNF', identity['key'][35:43]),
        ('natOp', invoice.get('natureza_operacao') or 'Venda de mercadoria'),
        ('mod', model), ('serie', identity['series']), ('nNF', identity['number']),
        ('dhEmi', identity['issued_at']), ('tpNF', '1'), ('idDest', dest_code),
        ('cMunFG', config['city_code']), ('tpImp', '4' if model == '65' else '1'), ('tpEmis', '1'),
        ('cDV', identity['key'][-1]), ('tpAmb', '1' if identity['environment'] == 'PRODUCAO' else '2'),
        ('finNFe', invoice.get('finalidade_emissao') or '1'),
        ('indFinal', required(invoice.get('consumidor_final'), 'indicador de consumidor final')),
        ('indPres', invoice.get('tipo_atendimento') or '0'), ('procEmi', '0'), ('verProc', 'ERP-UniNFe-1')]:
        add(ide, tag, value)
    if invoice.get('chave_referenciada'):
        add(SubElement(ide, 'NFref'), 'refNFe', digits(invoice['chave_referenciada'], 44, 'Chave referenciada'))
    emit = SubElement(info, 'emit')
    add(emit, 'CNPJ', digits(company.get('company_document'), 14, 'CNPJ do emitente'))
    add(emit, 'xNome', required(company.get('trade_name') or company.get('company_name'), 'razão social'))
    address(SubElement(emit, 'enderEmit'), company, 'emitente')
    add(emit, 'IE', required(company.get('state_registration'), 'inscrição estadual'))
    add(emit, 'CRT', crt)
    dest = SubElement(info, 'dest')
    doc = re.sub(r'[^0-9]', '', customer.get('documento') or '')
    if len(doc) not in {11, 14}:
        raise ValueError('Informe CPF/CNPJ do destinatário.')
    add(dest, 'CPF' if len(doc) == 11 else 'CNPJ', doc)
    add(dest, 'xNome', 'NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL'
        if identity['environment'] == 'HOMOLOGACAO' else required(customer.get('nome'), 'nome do destinatário'))
    address(SubElement(dest, 'enderDest'), customer, 'destinatário')
    ie = customer.get('inscricao_estadual')
    add(dest, 'indIEDest', '2' if ie == 'ISENTO' else ('1' if ie else '9'))
    if ie and ie != 'ISENTO':
        add(dest, 'IE', ie)
    weights = []
    for item in items:
        gross = Decimal(money(decimal(item.get('quantidade'), 'quantidade') * decimal(item.get('valor_unitario'), 'preço unitário')))
        discount = Decimal(money(decimal(item.get('desconto'), 'desconto', 0)))
        if discount > gross:
            raise ValueError('Desconto maior que o valor do item.')
        weights.append(gross - discount)
    invoice_discount = decimal(invoice.get('valor_desconto'), 'desconto da nota', 0)
    if invoice_discount > sum(weights):
        raise ValueError('Desconto da nota maior que o valor líquido dos produtos.')
    allocations = {tag: allocate(decimal(invoice.get(field), field, 0), weights)
                   for tag, field in [('vFrete', 'valor_frete'), ('vSeg', 'valor_seguro'),
                                      ('vOutro', 'valor_despesas'), ('vDesc', 'valor_desconto')]}
    totals = {key: Decimal('0') for key in ('vBC', 'vICMS', 'vProd', 'vDesc', 'vPIS', 'vCOFINS', 'vFrete', 'vSeg', 'vOutro')}
    for index, item in enumerate(items, 1):
        if decimal(item.get('ipi_percent'), 'IPI', 0):
            raise ValueError('IPI do item ainda precisa de integração tributária.')
        quantity = decimal(item.get('quantidade'), 'quantidade')
        if quantity == 0:
            raise ValueError('A quantidade deve ser maior que zero.')
        price = decimal(item.get('valor_unitario'), 'preço unitário')
        if quantity != quantity.quantize(Decimal('.0001')):
            raise ValueError('A quantidade aceita no máximo quatro casas decimais.')
        if price != price.quantize(Decimal('.0000000001')):
            raise ValueError('O preço unitário aceita no máximo dez casas decimais.')
        gross = Decimal(money(quantity * price))
        discount = Decimal(money(decimal(item.get('desconto'), 'desconto', 0))) + allocations['vDesc'][index - 1]
        if discount > gross:
            raise ValueError('Desconto maior que o valor do item.')
        extras = {tag: allocations[tag][index - 1] for tag in ('vFrete', 'vSeg', 'vOutro')}
        base = gross - discount + sum(extras.values())
        det = SubElement(info, 'det', nItem=str(index))
        prod = SubElement(det, 'prod')
        cfop = item.get('cfop') or config.get('cfop_internal' if dest_code == '1' else 'cfop_interstate')
        if not re.fullmatch(('5' if dest_code == '1' else '6') + r'[0-9]{3}', cfop or ''):
            raise ValueError('CFOP do item incompatível com o destino da operação.')
        unit = required(item.get('unidade'), 'unidade do produto')
        for tag, value in [('cProd', item.get('reference_id') or index), ('cEAN', 'SEM GTIN'),
            ('xProd', required(item.get('descricao'), 'descrição do produto')),
            ('NCM', digits(item.get('ncm'), 8, 'NCM')), ('CFOP', cfop), ('uCom', unit),
            ('qCom', format(quantity, '.4f')), ('vUnCom', format(price, '.10f')),
            ('vProd', money(gross)), ('cEANTrib', 'SEM GTIN'), ('uTrib', unit),
            ('qTrib', format(quantity, '.4f')), ('vUnTrib', format(price, '.10f'))]:
            add(prod, tag, value)
            if tag == 'NCM' and item.get('cest'):
                add(prod, 'CEST', digits(item['cest'], 7, 'CEST'))
        for tag in ('vFrete', 'vSeg'):
            if extras[tag]:
                add(prod, tag, money(extras[tag]))
        if discount:
            add(prod, 'vDesc', money(discount))
        if extras['vOutro']:
            add(prod, 'vOutro', money(extras['vOutro']))
        add(prod, 'indTot', '1')
        tax = SubElement(det, 'imposto')
        icms = SubElement(tax, 'ICMS')
        origin = required(item.get('origem', config.get('origin')), 'origem da mercadoria')
        if origin not in set('012345678'):
            raise ValueError('Origem da mercadoria inválida.')
        if crt in {'1', '4'}:
            code = required(item.get('csosn') or config.get('csosn'), 'CSOSN')
            if code not in {'101', '102', '103', '300', '400', '500'}:
                raise ValueError(f'CSOSN {code} precisa de implementação tributária específica.')
            group = SubElement(icms, 'ICMSSN' + (code if code in {'101', '500'} else '102'))
            add(group, 'orig', origin)
            add(group, 'CSOSN', code)
            if code == '101':
                credit = decimal(item.get('credit_rate', config.get('credit_rate')), 'alíquota de crédito do Simples')
                if credit > 100:
                    raise ValueError('Alíquota de crédito superior a 100%.')
                add(group, 'pCredSN', format(credit, '.4f'))
                add(group, 'vCredICMSSN', money(base * credit / 100))
            elif code == '500':
                retained_icms(group, item)
        else:
            code = required(item.get('icms_cst') or config.get('icms_cst'), 'CST ICMS')
            if code not in {'00', '40', '41', '50', '60'}:
                raise ValueError(f'CST ICMS {code} precisa de implementação tributária específica.')
            group = SubElement(icms, 'ICMS' + (code if code in {'00', '60'} else '40'))
            add(group, 'orig', origin)
            add(group, 'CST', code)
            if code == '60':
                retained_icms(group, item)
            if code == '00':
                rate = decimal(item.get('icms_rate', config.get('icms_rate')), 'alíquota ICMS')
                if rate > 100:
                    raise ValueError('Alíquota ICMS superior a 100%.')
                value = Decimal(money(base * rate / 100))
                for tag, amount in [('modBC', '3'), ('vBC', money(base)), ('pICMS', format(rate, '.4f')), ('vICMS', money(value))]:
                    add(group, tag, amount)
                totals['vBC'] += base
                totals['vICMS'] += value
        for name in ('PIS', 'COFINS'):
            field = name.lower()
            totals['v' + name] += contribution(tax, name, item.get(field + '_cst') or config.get(field + '_cst'),
                item.get(field + '_rate', config.get(field + '_rate')), base)
        totals['vProd'] += gross
        totals['vDesc'] += discount
        for tag, value in extras.items():
            totals[tag] += value
    total = SubElement(SubElement(info, 'total'), 'ICMSTot')
    amount = totals['vProd'] - totals['vDesc'] + totals['vFrete'] + totals['vSeg'] + totals['vOutro']
    for tag in ('vBC', 'vICMS', 'vICMSDeson', 'vFCP', 'vBCST', 'vST', 'vFCPST',
                'vFCPSTRet', 'vProd', 'vFrete', 'vSeg', 'vDesc', 'vII', 'vIPI',
                'vIPIDevol', 'vPIS', 'vCOFINS', 'vOutro', 'vNF'):
        add(total, tag, money(amount if tag == 'vNF' else totals.get(tag, Decimal('0'))))
    freight_mode = str(invoice.get('modalidade_frete') or '9')
    if freight_mode not in {'0', '1', '2', '3', '4', '9'}:
        raise ValueError('Modalidade de frete inválida.')
    if freight_mode == '9' and totals['vFrete']:
        raise ValueError('Selecione a modalidade de frete para informar seu valor.')
    add(SubElement(info, 'transp'), 'modFrete', freight_mode)
    payment = SubElement(SubElement(info, 'pag'), 'detPag')
    payment_code = required(invoice.get('payment_code'), 'código fiscal do pagamento')
    if payment_code not in {'01', '02', '15', '16', '17', '18', '19', '90', '99'}:
        raise ValueError('Forma de pagamento requer dados adicionais ainda não implementados.')
    add(payment, 'tPag', payment_code)
    if payment_code == '99':
        add(payment, 'xPag', required(invoice.get('forma_pagamento'), 'descrição do pagamento'))
    add(payment, 'vPag', '0.00' if payment_code == '90' else money(amount))
    if invoice.get('observacoes'):
        add(SubElement(info, 'infAdic'), 'infCpl', invoice['observacoes'])
    xml = '<?xml version="1.0" encoding="UTF-8"?>' + tostring(root, encoding='unicode')
    from .uninfe_schema import validate_unsigned
    validate_unsigned(xml)
    return xml
