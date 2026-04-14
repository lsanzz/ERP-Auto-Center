from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def only_digits(value: str | None) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def is_cnpj(value: str | None) -> bool:
    return len(only_digits(value)) == 14


def is_cpf(value: str | None) -> bool:
    return len(only_digits(value)) == 11


def _read_json(url: str, headers: dict | None = None, timeout: int = 10) -> dict:
    default_headers = {
        'User-Agent': 'ERP-Auto-Center/1.0',
        'Accept': 'application/json, text/plain, */*',
    }
    request = Request(url, headers=headers or default_headers)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def _build_address(data: dict) -> str:
    parts = [
        data.get('street') or data.get('logradouro'),
        data.get('number') or data.get('numero'),
        data.get('details') or data.get('complemento'),
        data.get('district') or data.get('bairro'),
        data.get('city') or data.get('municipio') or data.get('cidade'),
        data.get('state') or data.get('uf'),
        data.get('zip_code') or data.get('cep'),
    ]
    return ', '.join([str(part).strip() for part in parts if part])


def lookup_cnpj(document: str) -> dict:
    cnpj = only_digits(document)
    if len(cnpj) == 11:
        raise ValueError('CPF informado: a consulta automática é exclusiva para CNPJ.')
    if len(cnpj) != 14:
        raise ValueError('Informe um CNPJ com 14 dígitos.')

    urls = [
        f'https://brasilapi.com.br/api/cnpj/v1/{cnpj}',
        f'https://publica.cnpj.ws/cnpj/{cnpj}',
        f'https://receitaws.com.br/v1/cnpj/{cnpj}',
    ]
    last_error = None
    for url in urls:
        try:
            payload = _read_json(url)
            if 'estabelecimento' in payload:
                estabelecimento = payload.get('estabelecimento') or {}
                telefone = estabelecimento.get('telefone1') or estabelecimento.get('telefone2') or ''
                endereco = _build_address({
                    'logradouro': estabelecimento.get('logradouro'),
                    'numero': estabelecimento.get('numero'),
                    'complemento': estabelecimento.get('complemento'),
                    'bairro': estabelecimento.get('bairro'),
                    'municipio': (estabelecimento.get('cidade') or {}).get('nome'),
                    'uf': (estabelecimento.get('estado') or {}).get('sigla'),
                    'cep': estabelecimento.get('cep'),
                })
                return {
                    'cpf_cnpj': cnpj,
                    'nome': payload.get('razao_social') or estabelecimento.get('nome_fantasia') or '',
                    'nome_fantasia': estabelecimento.get('nome_fantasia') or '',
                    'telefone': telefone,
                    'email': estabelecimento.get('email') or '',
                    'endereco': endereco,
                    'situacao': (estabelecimento.get('situacao_cadastral') or 'ATIVA'),
                    'atividade_principal': ((estabelecimento.get('atividade_principal') or {}).get('descricao') or ''),
                }

            if payload.get('status') == 'ERROR':
                raise LookupError(payload.get('message') or 'CNPJ não encontrado.')

            atividade_principal = payload.get('cnae_fiscal_descricao') or ''
            if not atividade_principal and isinstance(payload.get('atividade_principal'), list) and payload.get('atividade_principal'):
                atividade_principal = payload.get('atividade_principal')[0].get('text') or ''

            telefone = payload.get('ddd_telefone_1') or payload.get('ddd_telefone_2') or ''
            if not telefone and payload.get('telefone'):
                telefone = payload.get('telefone')

            return {
                'cpf_cnpj': payload.get('cnpj') or cnpj,
                'nome': payload.get('razao_social') or payload.get('nome') or payload.get('fantasia') or payload.get('nome_fantasia') or '',
                'nome_fantasia': payload.get('nome_fantasia') or payload.get('fantasia') or '',
                'telefone': telefone,
                'email': payload.get('email') or '',
                'endereco': _build_address(payload),
                'situacao': payload.get('descricao_situacao_cadastral') or payload.get('situacao') or payload.get('situacao_cadastral') or '',
                'atividade_principal': atividade_principal,
            }
        except HTTPError as exc:
            last_error = exc
            if exc.code == 404:
                continue
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            continue

    if isinstance(last_error, HTTPError) and getattr(last_error, 'code', None) == 404:
        raise LookupError('CNPJ não encontrado.') from last_error
    raise RuntimeError('Falha ao consultar o serviço de CNPJ.') from last_error


def _best_phone(phones: list[dict]) -> str:
    for item in phones or []:
        ddd = str(item.get('DDD') or '').strip()
        numero = str(item.get('TELEFONE') or '').strip()
        if numero:
            return f'({ddd}) {numero}' if ddd else numero
    return ''


def _best_email(emails: list[dict]) -> str:
    if not emails:
        return ''
    ordered = sorted(emails, key=lambda item: (item.get('PRIORIDADE', 999), item.get('PESO', 999)))
    return ordered[0].get('EMAIL') or ''


def _best_address(addresses: list[dict]) -> str:
    if not addresses:
        return ''
    preferred = sorted(addresses, key=lambda item: (0 if str(item.get('TIPO_ENDERECO_ID')) == '1' else 1, item.get('DT_ATUALIZACAO') or ''))
    addr = preferred[0]
    return _build_address({
        'logradouro': f"{addr.get('LOGR_TIPO') or ''} {addr.get('LOGR_NOME') or ''}".strip(),
        'numero': addr.get('LOGR_NUMERO'),
        'complemento': addr.get('LOGR_COMPLEMENTO'),
        'bairro': addr.get('BAIRRO'),
        'municipio': addr.get('CIDADE'),
        'uf': addr.get('UF'),
        'cep': addr.get('CEP'),
    })


def lookup_cpf(document: str) -> dict:
    cpf = only_digits(document)
    if len(cpf) == 14:
        raise ValueError('CNPJ informado: esta consulta é exclusiva para CPF.')
    if len(cpf) != 11:
        raise ValueError('Informe um CPF com 11 dígitos.')

    token = os.getenv('DUALITY_TOKEN', 'DUALITY-FREE')
    base_url = os.getenv('DUALITY_BASE_URL', 'https://duality.lat/')
    url = f"{base_url}?{urlencode({'token': token, 'api': 'cpf', 'query': cpf})}"
    try:
        payload = _read_json(url)
    except HTTPError as exc:
        if exc.code == 404:
            raise LookupError('CPF não encontrado.') from exc
        raise RuntimeError('Falha ao consultar o serviço de CPF.') from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError('Serviço de consulta de CPF indisponível.') from exc

    dados = payload.get('DADOS') or {}
    if not dados:
        raise LookupError('CPF não encontrado.')

    return {
        'cpf_cnpj': dados.get('CPF') or cpf,
        'nome': dados.get('NOME') or '',
        'telefone': _best_phone(payload.get('TELEFONE') or []),
        'email': _best_email(payload.get('EMAIL') or []),
        'endereco': _best_address(payload.get('ENDERECOS') or []),
        'data_nascimento': dados.get('NASC') or '',
        'nome_mae': dados.get('NOME_MAE') or '',
        'raw': payload,
    }
