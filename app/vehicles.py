from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def only_plate_chars(value: str | None) -> str:
    return ''.join(ch for ch in str(value or '').upper() if ch.isalnum())


def lookup_plate(plate: str) -> dict:
    normalized_plate = only_plate_chars(plate)
    if len(normalized_plate) != 7:
        raise ValueError('Informe uma placa válida.')

    url_template = os.getenv('PLATE_API_URL')
    if not url_template:
        raise RuntimeError('Configure PLATE_API_URL para consultar placa sem OCR.')

    url = url_template.format(placa=quote(normalized_plate), plate=quote(normalized_plate))
    headers = {'Accept': 'application/json'}
    api_key = os.getenv('PLATE_API_KEY')
    if api_key:
        header_name = os.getenv('PLATE_API_HEADER', 'Authorization')
        header_value = os.getenv('PLATE_API_HEADER_VALUE') or f'Bearer {api_key}'
        headers[header_name] = header_value

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=int(os.getenv('PLATE_API_TIMEOUT', '10'))) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        if exc.code == 404:
            raise LookupError('Placa não encontrada.') from exc
        if exc.code in {401, 403}:
            raise RuntimeError('Chave da API de placa inválida ou sem permissão.') from exc
        raise RuntimeError('Falha ao consultar o serviço de placa.') from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError('Serviço de consulta de placa indisponível.') from exc

    return normalize_plate_payload(payload, normalized_plate)


def normalize_plate_payload(payload: dict, fallback_plate: str) -> dict:
    data = payload.get('data') if isinstance(payload.get('data'), dict) else payload
    if isinstance(data.get('vehicle_info'), dict):
        data = data['vehicle_info']
    if isinstance(data.get('veiculo'), dict):
        data = data['veiculo']
    if not isinstance(data, dict):
        raise LookupError('Placa não encontrada.')

    plate = only_plate_chars(_first_value(data, 'placa', 'plate')) or fallback_plate
    description_parts = [
        _first_value(data, 'marca', 'brand'),
        _first_value(data, 'modelo', 'model'),
        _first_value(data, 'versao', 'version'),
        _first_value(data, 'ano_modelo', 'model_year', 'ano', 'year'),
        _first_value(data, 'cor', 'color'),
    ]
    vehicle_description = ' '.join(part for part in description_parts if part).upper()

    return {
        'placa': plate,
        'veiculo_descricao': vehicle_description,
    }


def _first_value(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value not in (None, '', [], {}):
            return str(value).strip()
    return ''
