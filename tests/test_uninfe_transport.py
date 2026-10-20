from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest

from defusedxml.common import DefusedXmlException
from app.uninfe_transport import apply_protocol, collect_return, publish_invoice, request_situation

KEY = '35260912345678000190550010000000011000000010'


def document():
    return SimpleNamespace(access_key=KEY, environment='HOMOLOGACAO',
                           status='ENVIADO', xml_content='original',
                           response_payload=None, error_message=None)


def response(code='100', key=KEY, env='2', protocol='123456789012345'):
    return (f'<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">'
            f'<NFe><infNFe Id="NFe{key}"/></NFe><protNFe><infProt>'
            f'<tpAmb>{env}</tpAmb><chNFe>{key}</chNFe><cStat>{code}</cStat>'
            f'<nProt>{protocol}</nProt><xMotivo>Resultado</xMotivo>'
            '</infProt></protNFe></nfeProc>').encode()


class UniNFeTransportTests(unittest.TestCase):
    def test_situation_request_does_not_create_invoice(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {'send_directory': directory}
            target = request_situation(document(), config)
            self.assertEqual(target.name, KEY + '-ped-sit.xml')
            self.assertIn(b'<xServ>CONSULTAR</xServ>', target.read_bytes())
            self.assertEqual(request_situation(document(), config), target)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_situation_cancellation_and_unknown_key(self):
        for code, expected in [('101', 'CANCELADO'), ('217', 'ENVIADO')]:
            with tempfile.TemporaryDirectory() as directory:
                doc = document()
                xml = (f'<retConsSitNFe xmlns="http://www.portalfiscal.inf.br/nfe">'
                    f'<tpAmb>2</tpAmb><chNFe>{KEY}</chNFe><cStat>{code}</cStat></retConsSitNFe>')
                (Path(directory) / (KEY + '-sit.xml')).write_text(xml, encoding='utf-8')
                collect_return(doc, {'return_directory': directory, 'authorized_directory': directory})
                self.assertEqual(doc.status, expected)
                if code == '217':
                    self.assertIn('217', doc.error_message)

    def test_situation_wrong_environment_cannot_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            doc = document()
            xml = (f'<retConsSitNFe xmlns="http://www.portalfiscal.inf.br/nfe">'
                f'<tpAmb>1</tpAmb><chNFe>{KEY}</chNFe><cStat>101</cStat></retConsSitNFe>')
            (Path(directory) / (KEY + '-sit.xml')).write_text(xml, encoding='utf-8')
            with self.assertRaises(ValueError):
                collect_return(doc, {'return_directory': directory, 'authorized_directory': directory})
            self.assertEqual(doc.status, 'ENVIADO')

    def test_authorization_preserves_processed_xml(self):
        doc = document()
        self.assertTrue(apply_protocol(doc, response()))
        self.assertEqual(doc.status, 'AUTORIZADO')
        self.assertIn('nfeProc', doc.xml_content)

    def test_unrelated_invoice_is_ignored(self):
        doc = document()
        self.assertFalse(apply_protocol(doc, response(key='1' * 44)))
        self.assertEqual(doc.status, 'ENVIADO')

    def test_environment_and_protocol_required(self):
        for xml in (response(env='1'), response(protocol='')):
            doc = document()
            with self.assertRaises(ValueError):
                apply_protocol(doc, xml)
            self.assertEqual(doc.status, 'ENVIADO')

    def test_rejection_does_not_undo_authorization(self):
        doc = document()
        apply_protocol(doc, response())
        apply_protocol(doc, response(code='539'))
        self.assertEqual(doc.status, 'AUTORIZADO')

    def test_entity_expansion_is_rejected(self):
        with self.assertRaises(DefusedXmlException):
            apply_protocol(document(), b'<!DOCTYPE x [<!ENTITY x "bad">]><x>&x;</x>')

    def test_authorization_does_not_undo_cancellation(self):
        doc = document()
        doc.status = 'CANCELADO'
        apply_protocol(doc, response())
        self.assertEqual(doc.status, 'CANCELADO')

    def test_atomic_publication_is_idempotent_and_rejects_conflict(self):
        xml = (f'<NFe xmlns="http://www.portalfiscal.inf.br/nfe">'
               f'<infNFe Id="NFe{KEY}" versao="4.00">'
               '<ide><mod>55</mod><tpAmb>2</tpAmb></ide></infNFe></NFe>')
        with tempfile.TemporaryDirectory() as directory:
            config = {'send_directory': directory, 'document_models': '55'}
            target = publish_invoice(document(), config, xml)
            self.assertEqual(target.read_text(), xml)
            self.assertEqual(publish_invoice(document(), config, xml), target)
            with self.assertRaises(ValueError):
                publish_invoice(document(), config, xml.replace('</ide>', '<cNF>123</cNF></ide>'))
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_internal_xml_never_reaches_monitor(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                publish_invoice(document(), {'send_directory': directory}, '<fiscalDocument/>')
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_nested_authorized_and_pending_return(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {'authorized_directory': directory, 'return_directory': directory}
            doc = document()
            collect_return(doc, config)
            self.assertEqual(doc.status, 'ENVIADO')
            month = root / '202609'
            month.mkdir()
            (month / (KEY + '-procNFe.xml')).write_bytes(response())
            collect_return(doc, config)
            self.assertEqual(doc.status, 'AUTORIZADO')
