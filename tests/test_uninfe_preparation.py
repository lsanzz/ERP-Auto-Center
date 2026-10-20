import json
import unittest
from datetime import datetime
from unittest.mock import Mock

from app import create_app
from app.models import FiscalDocument, SystemSettings, UniNFeSubmission, db
from app.uninfe_preparation import access_key, prepare


class UniNFePreparationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'APP_ENV': 'testing',
            'AUTO_CREATE_SCHEMA': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
            'SQLALCHEMY_ENGINE_OPTIONS': {}})
        self.context = self.app.app_context()
        self.context.push()
        self.settings = SystemSettings(company_name='Teste', company_document='06117473000150', state='PR',
            uninfe_settings_json=json.dumps(dict(environment='HOMOLOGACAO', document_models='55',
                nfe_series=1, nfe_next_number=1)))
        db.session.add(self.settings)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def new_document(self):
        doc = FiscalDocument(provider_name='UNINFE', document_type='NFE',
            environment='HOMOLOGACAO', status='PRONTO_PARA_ENVIO', request_payload='{}')
        db.session.add(doc)
        db.session.commit()
        return doc

    def test_known_access_key(self):
        self.assertEqual(access_key('PR', datetime(2017, 7, 1), '06117473000150',
            '55', 1, 46319, '91275654'), '41170706117473000150550010000463191912756548')

    def test_company_uf_and_city_code_must_match(self):
        from app.uninfe_config import save_config
        config = dict(environment='HOMOLOGACAO', certificate_type='A1',
            document_models='55', city_code='3509502', nfe_series='1', nfce_series='1',
            nfe_next_number='1', nfce_next_number='1')
        previous = self.settings.uninfe_settings_json
        with self.assertRaises(ValueError):
            save_config(self.settings, config)
        self.assertEqual(previous, self.settings.uninfe_settings_json)

    def test_uninfe_switch_clears_focus_credentials_and_blocks_calls(self):
        from app.models import FiscalApiConfig
        from app.uninfe_config import save_config
        from app.company_focus import focus_request
        from app.fiscal import _focus_url, save_fiscal_config_from_form
        config = FiscalApiConfig(provider_name='FOCUSNFE', api_token='old-token',
            api_base_url='https://example.com', focus_management_token='old-management')
        db.session.add(config)
        db.session.commit()
        save_config(self.settings, dict(environment='HOMOLOGACAO', certificate_type='A1',
            document_models='55', city_code='4106902', nfe_series='1', nfce_series='1',
            nfe_next_number='1', nfce_next_number='1'))
        db.session.commit()
        self.assertIsNone(config.api_token)
        self.assertIsNone(config.api_base_url)
        self.assertIsNone(config.focus_management_token)
        with self.assertRaises(ValueError):
            focus_request('unused', '')
        with self.assertRaises(ValueError):
            _focus_url(config, '/v2/nfe')
        with self.assertRaises(ValueError):
            save_fiscal_config_from_form({'provider_name': 'FOCUSNFE'})

    def test_retry_reuses_snapshot_and_number_after_company_edit(self):
        doc = self.new_document()
        builder = Mock(return_value='<prepared/>')
        first = prepare(doc.id, builder)
        db.session.commit()
        identity = (first.access_key, first.prepared_xml, first.snapshot_json)
        self.settings.company_name = 'Changed'
        db.session.commit()
        second = prepare(doc.id, builder)
        self.assertEqual((second.access_key, second.prepared_xml, second.snapshot_json), identity)
        self.assertEqual(builder.call_count, 1)
        self.assertEqual(json.loads(self.settings.uninfe_settings_json)['nfe_next_number'], 2)

    def test_failed_builder_does_not_consume_number(self):
        doc = self.new_document()
        with self.assertRaises(ValueError):
            prepare(doc.id, Mock(side_effect=ValueError('Invalid tax rule')))
        db.session.rollback()
        self.assertEqual(UniNFeSubmission.query.count(), 0)
        self.assertEqual(json.loads(self.settings.uninfe_settings_json)['nfe_next_number'], 1)
        self.assertIsNone(doc.access_key)

    def test_stale_counter_does_not_reuse_reserved_number(self):
        doc = self.new_document()
        prepare(doc.id, Mock(return_value='<prepared/>'))
        db.session.commit()
        config = json.loads(self.settings.uninfe_settings_json)
        config['nfe_next_number'] = 1
        self.settings.uninfe_settings_json = json.dumps(config)
        db.session.commit()
        second = prepare(self.new_document().id, Mock(return_value='<prepared/>'))
        self.assertEqual(second.number, 2)

    def test_prepared_invoice_rejects_form_changes(self):
        from app.fiscal import apply_invoice_form
        doc = self.new_document()
        prepare(doc.id, Mock(return_value='<prepared/>'))
        db.session.commit()
        with self.assertRaises(ValueError):
            apply_invoice_form(doc, {})

    def test_fiscal_form_preserves_structured_address_and_payment(self):
        from werkzeug.datastructures import MultiDict
        from app.fiscal import apply_invoice_form
        doc = self.new_document()
        apply_invoice_form(doc, MultiDict({
            'fiscal_customer_documento': '12345678901',
            'fiscal_customer_address': 'Rua A', 'fiscal_customer_address_number': '10',
            'fiscal_customer_neighborhood': 'Centro', 'fiscal_customer_city': 'Curitiba',
            'fiscal_customer_city_code': '4106902', 'fiscal_customer_state': 'pr',
            'fiscal_customer_zip_code': '80010000',
            'payment_code': '01', 'consumidor_final': '1',
        }))
        db.session.commit()
        payload = json.loads(doc.request_payload)
        self.assertEqual(payload['customer']['state'], 'PR')
        self.assertEqual(payload['customer']['city_code'], '4106902')
        self.assertEqual(payload['customer']['address_number'], '10')
        self.assertEqual(payload['invoice']['payment_code'], '01')
        self.assertEqual(payload['invoice']['consumidor_final'], '1')

    def test_fiscal_fields_render_saved_data(self):
        from flask import render_template
        from types import SimpleNamespace
        with self.app.test_request_context():
            html = render_template('fiscal/_uninfe_customer.html',
                config=SimpleNamespace(provider_name='UNINFE'),
                customer={'address': 'Rua & Avenida', 'city_code': '4106902'},
                invoice={'payment_code': '01', 'consumidor_final': '1'})
        self.assertIn('Rua &amp; Avenida', html)
        self.assertIn('value="4106902"', html)
        self.assertIn('name="payment_code"', html)

    def test_item_tax_fields_render_and_persist(self):
        from flask import render_template
        from types import SimpleNamespace
        from werkzeug.datastructures import MultiDict
        from app.fiscal import apply_invoice_form
        doc = self.new_document()
        doc.request_payload = json.dumps({'items': {'parts': [{'descricao': 'Filtro'}]}})
        form = MultiDict({'fiscal_item_csosn': '500', 'fiscal_item_cest': '0100100',
                         'fiscal_item_vBCSTRet': '25', 'fiscal_item_pST': '18',
                         'fiscal_item_vICMSSTRet': '2.50'})
        apply_invoice_form(doc, form)
        db.session.commit()
        items = json.loads(doc.request_payload)['items']['parts']
        self.assertEqual(items[0]['csosn'], '500')
        self.assertEqual(items[0]['vICMSSTRet'], '2.50')
        with self.app.test_request_context():
            html = render_template('fiscal/_uninfe_item_taxes.html',
                config=SimpleNamespace(provider_name='UNINFE'), all_items=items)
        self.assertIn('value="2.50"', html)
        self.assertIn('value="500"', html)
