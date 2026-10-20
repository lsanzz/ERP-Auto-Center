import unittest
import os
from unittest.mock import patch

from tests import test_app
from app.models import FiscalApiConfig, SystemSettings, db
from app.uninfe_config import get_config, save_config
from app.settings import get_system_settings


class UniNFeConfigTests(unittest.TestCase):
    setUp = test_app.ERPAppTestCase.setUp
    tearDown = test_app.ERPAppTestCase.tearDown
    login_web = test_app.ERPAppTestCase.login_web

    def test_legacy_environment_cannot_activate_or_overwrite_provider(self):
        from app.fiscal import get_fiscal_config
        with self.app.app_context(), patch.dict(os.environ, {
            'FOCUS_NFE_TOKEN': 'legacy-environment-token',
            'FOCUS_NFE_ENVIRONMENT': 'PRODUCAO',
        }):
            self.assertIsNone(get_fiscal_config())
            self.assertEqual(FiscalApiConfig.query.count(), 0)
            config = FiscalApiConfig(provider_name='FOCUSNFE', active=False,
                environment='HOMOLOGACAO', api_token='stored-token')
            db.session.add(config)
            db.session.commit()
            self.assertIs(get_fiscal_config(), config)
            self.assertEqual(config.api_token, 'stored-token')
            self.assertEqual(config.environment, 'HOMOLOGACAO')
            self.assertFalse(config.active)

    def test_company_save_without_provider_never_attempts_focus_sync(self):
        self.login_web()
        with patch('app.company_focus.sync_company') as sync:
            response = self.client.post('/configuracoes/empresa', data={
                'company_name': 'Oficina sem provedor'}, follow_redirects=True)
            sync.assert_not_called()
        self.assertIn('Dados da empresa salvos.'.encode(), response.data)

    def config_form(self):
        return dict(environment='HOMOLOGACAO', certificate_type='A3',
                    document_models='55,65', city_code='3509502',
                    nfe_series='1', nfce_series='2', nfe_next_number='42',
                    nfce_next_number='1', cfop_internal='5102',
                    csosn='102', pis_rate='0', accountant_rules='Orientação do contador')

    def test_configuration_persists_and_selects_uninfe(self):
        self.login_web()
        response = self.client.post('/configuracoes/empresa/uninfe', data=self.config_form(), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            settings = SystemSettings.query.first()
            values = get_config(settings)
            self.assertEqual(values['certificate_type'], 'A3')
            self.assertEqual(values['nfe_next_number'], 42)
            self.assertEqual(values['document_models'], '55,65')
            self.assertEqual(values['accountant_rules'], 'Orientação do contador')
            self.assertEqual(FiscalApiConfig.query.first().provider_name, 'UNINFE')
        self.assertIn(b'UniNFe e regras fiscais', response.data)

    def test_invalid_configuration_does_not_replace_existing(self):
        with self.app.app_context():
            settings = get_system_settings()
            save_config(settings, self.config_form())
            db.session.commit()
            previous = settings.uninfe_settings_json
            for field, value in [('city_code', '123'), ('pis_rate', 'NaN'),
                                 ('nfe_next_number', '0'), ('certificate_type', 'A4')]:
                with self.assertRaises(ValueError):
                    save_config(settings, self.config_form() | {field: value})
                self.assertEqual(settings.uninfe_settings_json, previous)

    def test_save_company_does_not_contact_focus_after_switch(self):
        self.login_web()
        self.client.post('/configuracoes/empresa/uninfe', data=self.config_form())
        with patch('app.company_focus.sync_company') as sync:
            self.client.post('/configuracoes/empresa', data={'company_name': 'Oficina', 'tax_regime': '1', 'state': 'SP', 'city': 'Campinas'})
            sync.assert_not_called()

    def test_company_uf_change_requires_new_municipality_without_losing_rules(self):
        self.login_web()
        self.client.post('/configuracoes/empresa/uninfe', data=self.config_form())
        response = self.client.post('/configuracoes/empresa', data={
            'company_name': 'Oficina PR', 'tax_regime': '1', 'state': 'PR',
            'city': 'Curitiba'}, follow_redirects=True)
        self.assertIn('A UF ou o município mudou.'.encode(), response.data)
        with self.app.app_context():
            settings = SystemSettings.query.first()
            values = get_config(settings)
            self.assertEqual(settings.state, 'PR')
            self.assertEqual(values['city_code'], '')
            self.assertEqual(values['certificate_type'], 'A3')
            self.assertEqual(values['nfe_next_number'], 42)
            self.assertEqual(values['csosn'], '102')
        form = self.config_form() | {'city_code': '4106902'}
        self.client.post('/configuracoes/empresa/uninfe', data=form)
        with self.app.app_context():
            self.assertEqual(get_config(SystemSettings.query.first())['city_code'], '4106902')

    def test_invalid_company_edit_rolls_back_with_uninfe_enabled(self):
        self.login_web()
        self.client.post('/configuracoes/empresa/uninfe', data=self.config_form())
        with self.app.app_context():
            original = SystemSettings.query.first().company_name
        for state, regime in [('ZZ', '1'), ('SP', '9'), ('SP', '')]:
            self.client.post('/configuracoes/empresa', data={
                'company_name': 'Must not persist', 'tax_regime': regime, 'state': state})
            with self.app.app_context():
                settings = SystemSettings.query.first()
                self.assertEqual(settings.company_name, original)
                self.assertEqual(get_config(settings)['city_code'], '3509502')

    def test_municipality_change_in_same_uf_invalidates_ibge(self):
        self.login_web()
        with self.app.app_context():
            settings = get_system_settings()
            settings.state, settings.city, settings.tax_regime = 'SP', 'Campinas', '1'
            db.session.add(settings)
            db.session.commit()
        self.client.post('/configuracoes/empresa/uninfe', data=self.config_form())
        response = self.client.post('/configuracoes/empresa', data={
            'company_name': 'Oficina', 'tax_regime': '1', 'state': 'SP',
            'city': 'Santos'}, follow_redirects=True)
        self.assertIn('A UF ou o município mudou.'.encode(), response.data)
        with self.app.app_context():
            self.assertEqual(get_config(get_system_settings())['city_code'], '')

    def test_city_capitalization_does_not_invalidate_ibge(self):
        self.login_web()
        with self.app.app_context():
            settings = get_system_settings()
            settings.state, settings.city, settings.tax_regime = 'SP', 'Campinas', '1'
            db.session.add(settings)
            db.session.commit()
        self.client.post('/configuracoes/empresa/uninfe', data=self.config_form())
        self.client.post('/configuracoes/empresa', data={
            'company_name': 'Oficina', 'tax_regime': '1', 'state': 'SP',
            'city': '  CAMPINAS  '})
        with self.app.app_context():
            self.assertEqual(get_config(get_system_settings())['city_code'], '3509502')
