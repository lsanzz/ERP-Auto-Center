"""Run on Windows: python uninfe_connector.py --config connector.json --once.

Only outbound HTTPS is used. No web server, ERP database password or certificate
private key is needed. Install the repository's Python requirements first.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
from types import SimpleNamespace
from urllib import request
from urllib.parse import urlsplit

from app.uninfe_transport import collect_return, publish_invoice, _directory


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward the bearer token to another URL.


class Client:
    def __init__(self, config):
        base = config['erp_url'].rstrip('/')
        parts = urlsplit(base)
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment):
            raise ValueError('A URL do ERP deve usar HTTPS, sem credenciais, query ou fragmento.')
        self.base = base + '/api/uninfe-connector'
        self.identity = config['connector_id']
        self.token = os.environ.get('UNINFE_CONNECTOR_TOKEN', '')
        if len(self.token) < 32:
            raise ValueError('Defina UNINFE_CONNECTOR_TOKEN com a credencial fornecida pela hospedagem.')
        self.opener = request.build_opener(NoRedirect)

    def call(self, path, method='GET', body=None, xml=False):
        data = body if xml else json.dumps(body).encode() if body is not None else None
        req = request.Request(self.base + path, data=data, method=method, headers={
            'Authorization': 'Bearer ' + self.token, 'X-Connector-ID': self.identity,
            'Content-Type': 'application/xml' if xml else 'application/json',
            'Accept': 'application/json',
        })
        with self.opener.open(req, timeout=30) as response:
            result = response.read(32 * 1024 * 1024 + 1)
        if len(result) > 32 * 1024 * 1024:
            raise ValueError('Resposta do ERP excedeu o limite do conector.')
        return json.loads(result)


def process_task(client, task_id, folders):
    task = client.call(f'/tasks/{task_id}')
    if task['status'] == 'DONE':
        return
    key = task['key']
    if (not re.fullmatch(r'[0-9]{44}', key) or task['environment'] != 'HOMOLOGACAO'
            or task['model'] not in {'55', '65'} or key[20:22] != task['model']):
        raise ValueError('Identidade fiscal inválida recebida do ERP.')
    if hashlib.sha256(task['xml'].encode()).hexdigest() != task['sha256']:
        raise ValueError('O XML recebido diverge do hash reservado.')
    config = dict(folders, document_models=task['model'])
    for field in ('send_directory', 'return_directory', 'authorized_directory'):
        _directory(config, field)
    document = SimpleNamespace(access_key=key, environment=task['environment'],
        status='ENVIADO', xml_content=None, response_payload=None, error_message=None)
    # Server durably consumes the permission BEFORE local publication. A lost
    # response or a crash may require investigation, but cannot grant a replay.
    permission = client.call(f'/tasks/{task_id}/start', method='POST')
    if permission['publish']:
        try:
            publish_invoice(document, config, task['xml'])
        except Exception:
            client.call(f'/tasks/{task_id}/problem', method='POST', body={
                'error': 'Publicação inconclusiva. Verifique a pasta e os retornos do UniNFe; não reenvie a nota automaticamente.'})
            raise
        client.call(f'/tasks/{task_id}/published', method='POST')
    collect_return(document, config)
    if document.response_payload:
        client.call(f'/tasks/{task_id}/result', method='POST',
                    body=document.response_payload.encode('utf-8'), xml=True)
    elif document.error_message:
        client.call(f'/tasks/{task_id}/problem', method='POST', body={'error': document.error_message})


def poll(client, folders):
    after = 0
    while True:
        tasks = client.call(f'/tasks?after={after}')['tasks']
        if not tasks:
            return
        for task_id in tasks:
            try:
                process_task(client, task_id, folders)
            except Exception as exc:
                # No raw HTTP responses, tokens, XMLs, or private taxpayer data.
                print(f'Tarefa {task_id}: falha ({type(exc).__name__}); confira o ERP e o UniNFe.')
        after = max(tasks)


def main():
    parser = argparse.ArgumentParser(description='Conector Windows → ERP → UniNFe (homologação).')
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    client = Client(config)
    for field in ('send_directory', 'return_directory', 'authorized_directory'):
        _directory(config, field)
    print('Conector ativo em homologação. Encerre com Ctrl+C.')
    while True:
        try:
            poll(client, config)
        except Exception as exc:
            print(f'Comunicação indisponível ({type(exc).__name__}); nova tentativa em 15 segundos.')
        if args.once:
            return
        time.sleep(15)


if __name__ == '__main__':
    main()
