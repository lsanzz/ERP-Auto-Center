from copy import deepcopy
import unittest
from defusedxml import ElementTree as ET

from app.uninfe_xml import build_invoice

NS = {'n': 'http://www.portalfiscal.inf.br/nfe'}


class UniNFeXmlTests(unittest.TestCase):
    def setUp(self):
        self.company = dict(company_name='Oficina & Cia', company_document='06117473000150',
            state_registration='123456789', tax_regime='1', address='Rua A', address_number='1',
            neighborhood='Centro', city='Curitiba', state='PR', zip_code='80010000')
        self.config = dict(city_code='4106902', origin='0', csosn='102', pis_cst='07', cofins_cst='07')
        self.payload = dict(customer=self.company | dict(documento='12345678901', nome='Cliente', city_code='4106902'),
            invoice=dict(consumidor_final='1', payment_code='01'),
            items=dict(parts=[dict(descricao='Peça & filtro', reference_id='P1', ncm='84212300',
                cfop='5102', unidade='UN', quantidade='2', valor_unitario='10.25', desconto='0.50')]))
        self.identity = dict(key='41170706117473000150550010000463191912756548', model='55',
            series=1, number=46319, issued_at='2017-07-01T12:00:00-03:00', environment='HOMOLOGACAO')

    def build(self):
        return ET.fromstring(build_invoice(self.payload, self.company, self.config, self.identity))

    def test_xml_totals_escape_and_homologation_name(self):
        root = self.build()
        self.assertEqual(root.findtext('.//n:vNF', namespaces=NS), '20.00')
        self.assertEqual(root.findtext('.//n:vProd', namespaces=NS), '20.50')
        self.assertEqual(root.findtext('.//n:emit/n:xNome', namespaces=NS), 'Oficina & Cia')
        self.assertIn('SEM VALOR FISCAL', root.findtext('.//n:dest/n:xNome', namespaces=NS))
        self.assertEqual(root.findtext('.//n:ICMSSN102/n:CSOSN', namespaces=NS), '102')

    def test_generated_xml_validates_before_signature(self):
        from app.uninfe_schema import validate_unsigned
        validate_unsigned(build_invoice(self.payload, self.company, self.config, self.identity))

    def test_nfce_model_and_print_format_validate_before_monitor_qrcode(self):
        from app.uninfe_preparation import access_key
        from datetime import datetime
        self.identity.update(model='65', key=access_key('PR', datetime(2017, 7, 1),
            '06117473000150', '65', 1, 46319, '91275654'))
        self.payload['invoice']['tipo_atendimento'] = '1'
        root = self.build()
        self.assertEqual(root.findtext('.//n:mod', namespaces=NS), '65')
        self.assertEqual(root.findtext('.//n:tpImp', namespaces=NS), '4')
        self.assertIsNone(root.find('n:infNFeSupl', NS))

    def test_nfce_rejects_non_final_consumer(self):
        self.identity['model'] = '65'
        self.payload['invoice']['consumidor_final'] = '0'
        with self.assertRaises(ValueError):
            self.build()

    def test_schema_rejects_missing_mandatory_group(self):
        from app.uninfe_schema import validate_unsigned
        root = self.build()
        info = root.find('n:infNFe', NS)
        info.remove(info.find('n:emit', NS))
        with self.assertRaises(ValueError):
            validate_unsigned(ET.tostring(root))

    def test_normal_regime_uses_configured_rates(self):
        self.company['tax_regime'] = '3'
        self.config.update(icms_cst='00', icms_rate='18', pis_cst='01', pis_rate='1.65',
                           cofins_cst='01', cofins_rate='7.6')
        root = self.build()
        self.assertEqual(root.findtext('.//n:ICMSTot/n:vICMS', namespaces=NS), '3.60')
        self.assertEqual(root.findtext('.//n:ICMSTot/n:vPIS', namespaces=NS), '0.33')
        self.assertEqual(root.findtext('.//n:ICMSTot/n:vCOFINS', namespaces=NS), '1.52')

    def test_missing_address_is_not_replaced_with_default_city(self):
        del self.payload['customer']['city_code']
        with self.assertRaises(ValueError):
            self.build()

    def test_simples_credit_uses_configured_percentage(self):
        self.config.update(csosn='101', credit_rate='3.25')
        root = self.build()
        self.assertEqual(root.findtext('.//n:ICMSSN101/n:vCredICMSSN', namespaces=NS), '0.65')

    def test_previously_retained_st_is_not_charged_again(self):
        item = self.payload['items']['parts'][0]
        item.update(cest='0100100', vBCSTRet='25', pST='18', vICMSSubstituto='2', vICMSSTRet='2.50')
        for crt, code in [('1', '500'), ('3', '60')]:
            self.company['tax_regime'] = crt
            self.config.update(csosn=code, icms_cst=code)
            root = self.build()
            self.assertEqual(root.findtext('.//n:vICMSSTRet', namespaces=NS), '2.50')
            self.assertEqual(root.findtext('.//n:ICMSTot/n:vST', namespaces=NS), '0.00')
            self.assertEqual(root.findtext('.//n:vNF', namespaces=NS), '20.00')

    def test_partial_retained_st_group_is_rejected(self):
        self.config['csosn'] = '500'
        self.payload['items']['parts'][0]['vBCSTRet'] = '25'
        with self.assertRaises(ValueError):
            self.build()

    def test_tax_classification_is_required(self):
        self.config['csosn'] = ''
        with self.assertRaises(ValueError):
            self.build()

    def test_freight_cannot_be_silently_omitted(self):
        self.payload['invoice']['valor_frete'] = '50'
        with self.assertRaises(ValueError):
            self.build()

    def test_invoice_costs_and_discount_reconcile_exactly(self):
        self.payload['items']['parts'] *= 3
        self.payload['invoice'].update(valor_frete='1.00', valor_seguro='0.01',
            valor_despesas='0.02', valor_desconto='0.05', modalidade_frete='0')
        root = self.build()
        from decimal import Decimal
        for tag, expected in [('vFrete', '1.00'), ('vSeg', '0.01'), ('vOutro', '0.02'), ('vDesc', '1.55')]:
            values = root.findall(f'.//n:det/n:prod/n:{tag}', NS)
            self.assertEqual(sum(Decimal(node.text) for node in values), Decimal(expected))
            self.assertEqual(root.findtext(f'.//n:ICMSTot/n:{tag}', namespaces=NS), expected)
        self.assertEqual(root.findtext('.//n:vNF', namespaces=NS), '60.98')
        self.assertEqual(root.findtext('.//n:vPag', namespaces=NS), '60.98')

    def test_invoice_discount_cannot_exceed_items_net_value(self):
        self.payload['invoice']['valor_desconto'] = '20.01'
        with self.assertRaises(ValueError):
            self.build()

    def test_negative_nan_and_excessive_discount_rejected(self):
        original = deepcopy(self.payload)
        for field, value in [('quantidade', '-1'), ('valor_unitario', 'NaN'), ('desconto', '25')]:
            self.payload = deepcopy(original)
            self.payload['items']['parts'][0][field] = value
            with self.assertRaises(ValueError):
                self.build()
