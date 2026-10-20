from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.models import UniNFeRelayTask, UniNFeSubmission, db
from app.uninfe_dispatch import issue, consult
from tests import test_uninfe_dispatch
from tests.test_uninfe_transport import response
from uninfe_connector import process_task, NoRedirect

PREFIX = '/api/uninfe-connector'


class UniNFeRelayTests(unittest.TestCase):
    setUp = test_uninfe_dispatch.UniNFeDispatchTests.setUp
    tearDown = test_uninfe_dispatch.UniNFeDispatchTests.tearDown
    new_document = test_uninfe_dispatch.UniNFeDispatchTests.new_document
    setup_invoice = test_uninfe_dispatch.UniNFeDispatchTests.setup_invoice

    def remote_invoice(self, directory):
        self.app.config.update(UNINFE_TRANSPORT='remote', UNINFE_CONNECTOR_ID='office-windows',
                               UNINFE_CONNECTOR_TOKEN='x' * 48)
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer ' + 'x' * 48, 'X-Connector-ID': 'office-windows'}
        document = self.setup_invoice(directory)
        with patch('app.uninfe_dispatch._directory', side_effect=AssertionError('Hosted server read a Windows path')):
            issue(document.id)
        return document, UniNFeSubmission.query.one().id

    def call(self, path, method='GET', body=None, xml=False):
        kwargs = {'data': body, 'content_type': 'application/xml'} if xml else {'json': body}
        result = self.client.open(PREFIX + path, method=method, headers=self.headers, **kwargs)
        if result.status_code != 200:
            raise AssertionError(f'HTTP {result.status_code}: {result.get_data(as_text=True)}')
        return result.get_json()

    def test_remote_queue_and_one_shot_delivery_permission(self):
        with TemporaryDirectory() as directory:
            doc, task_id = self.remote_invoice(directory)
            self.assertEqual(doc.status, 'AGUARDANDO_CONECTOR')
            self.assertEqual(list(Path(directory).iterdir()), [])
            issue(doc.id)
            self.assertEqual(UniNFeRelayTask.query.count(), 1)
            self.assertEqual(self.call('/tasks')['tasks'], [task_id])
            self.assertTrue(self.call(f'/tasks/{task_id}/start', 'POST')['publish'])
            self.assertFalse(self.call(f'/tasks/{task_id}/start', 'POST')['publish'])
            self.assertIsNotNone(db.session.get(UniNFeSubmission, task_id).publication_started_at)
            with patch('app.uninfe_dispatch.collect_return', side_effect=AssertionError):
                consult(doc)

    def test_authentication_is_mandatory_even_without_csrf(self):
        with TemporaryDirectory() as directory:
            _, task_id = self.remote_invoice(directory)
            self.assertEqual(self.client.get(PREFIX + '/tasks').status_code, 401)
            self.assertEqual(self.client.post(PREFIX + f'/tasks/{task_id}/start').status_code, 401)
            wrong = dict(self.headers, **{'X-Connector-ID': 'another-office'})
            self.assertEqual(self.client.get(PREFIX + '/tasks', headers=wrong).status_code, 401)
            self.assertEqual(UniNFeRelayTask.query.one().status, 'WAITING')

    def test_windows_publishes_once_and_archives_return_in_hosted_erp(self):
        with TemporaryDirectory() as directory:
            doc, task_id = self.remote_invoice(directory)
            folders = {name: directory for name in ('send_directory', 'return_directory', 'authorized_directory')}
            process_task(self, task_id, folders)
            sent = Path(directory) / (doc.access_key + '-nfe.xml')
            self.assertTrue(sent.exists())
            sent.unlink()  # Simulate UniNFe consuming the request.
            process_task(self, task_id, folders)
            self.assertFalse(sent.exists())
            returned = response(key=doc.access_key)
            (Path(directory) / (doc.access_key + '-procNFe.xml')).write_bytes(returned)
            process_task(self, task_id, folders)
            db.session.refresh(doc)
            self.assertEqual(doc.status, 'AUTORIZADO')
            self.assertEqual(doc.xml_content, returned.decode())
            self.assertEqual(UniNFeRelayTask.query.one().status, 'DONE')
            self.assertEqual(self.call('/tasks')['tasks'], [])

    def test_mismatched_return_does_not_change_invoice(self):
        with TemporaryDirectory() as directory:
            doc, task_id = self.remote_invoice(directory)
            self.call(f'/tasks/{task_id}/start', 'POST')
            result = self.client.post(PREFIX + f'/tasks/{task_id}/result',
                data=response(key='1' * 44), content_type='application/xml', headers=self.headers)
            self.assertEqual(result.status_code, 422)
            db.session.refresh(doc)
            self.assertEqual(doc.status, 'PROCESSANDO')

    def test_lost_start_response_does_not_republish(self):
        with TemporaryDirectory() as directory:
            doc, task_id = self.remote_invoice(directory)
            self.call(f'/tasks/{task_id}/start', 'POST')  # Response lost before publication.
            folders = {name: directory for name in ('send_directory', 'return_directory', 'authorized_directory')}
            process_task(self, task_id, folders)
            self.assertFalse((Path(directory) / (doc.access_key + '-nfe.xml')).exists())

    def test_no_redirect_can_forward_credentials(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, None, None, 'https://other.example'))

    def test_http_rejected_outside_test_mode(self):
        with TemporaryDirectory() as directory:
            self.remote_invoice(directory)
            self.app.config['TESTING'] = False
            try:
                self.assertEqual(self.client.get(PREFIX + '/tasks', headers=self.headers).status_code, 403)
                self.assertEqual(self.client.get(PREFIX + '/tasks', headers=self.headers,
                                                 base_url='https://localhost').status_code, 200)
            finally:
                self.app.config['TESTING'] = True

    def test_wrong_environment_and_xml_entities_are_rejected(self):
        with TemporaryDirectory() as directory:
            doc, task_id = self.remote_invoice(directory)
            self.call(f'/tasks/{task_id}/start', 'POST')
            for xml in (response(key=doc.access_key, env='1'),
                        b'<!DOCTYPE a [<!ENTITY e "expanded">]><a>&e;</a>', b'<broken'):
                result = self.client.post(PREFIX + f'/tasks/{task_id}/result',
                    data=xml, content_type='application/xml', headers=self.headers)
                self.assertEqual(result.status_code, 422)
                db.session.refresh(doc)
                self.assertEqual(doc.status, 'PROCESSANDO')
