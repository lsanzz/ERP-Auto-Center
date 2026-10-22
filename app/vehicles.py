from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


def only_plate_chars(value: str | None) -> str:
    return ''.join(ch for ch in str(value or '').upper() if ch.isalnum())


def lookup_plate(plate: str) -> dict:
    normalized_plate = only_plate_chars(plate)
    if len(normalized_plate) != 7 or not normalized_plate.isalnum():
        raise ValueError('Informe uma placa válida.')

    url_template = os.getenv('PLATE_API_URL')
    api_token = os.getenv('PLATE_API_TOKEN')
    if not url_template and api_token:
        url_template = 'https://wdapi2.com.br/consulta/{placa}/' + api_token
    if not url_template:
        raise RuntimeError('Configure PLATE_API_URL e PLATE_API_TOKEN para consultar placa.')

    url = url_template.format(placa=quote(normalized_plate), plate=quote(normalized_plate))
    try:
        parsed_url = urlsplit(url)
    except ValueError as exc:
        raise RuntimeError('PLATE_API_URL inválida.') from exc
    if parsed_url.scheme != 'https' or not parsed_url.hostname or parsed_url.username or parsed_url.password:
        raise RuntimeError('PLATE_API_URL deve usar HTTPS e não pode conter credenciais.')
    headers = {'Accept': 'application/json'}
    api_key = os.getenv('PLATE_API_KEY')
    if api_key:
        header_name = os.getenv('PLATE_API_HEADER', 'Authorization')
        header_value = os.getenv('PLATE_API_HEADER_VALUE') or f'Bearer {api_key}'
        headers[header_name] = header_value

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=int(os.getenv('PLATE_API_TIMEOUT', '10'))) as response:  # nosec B310
            payload = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        if exc.code == 401:
            raise ValueError('Placa inválida. Use o formato AAA0X00 ou AAA9999.') from exc
        if exc.code == 402:
            raise RuntimeError('Token da API de placa inválido.') from exc
        if exc.code == 406:
            raise LookupError('Nenhum resultado encontrado para esta placa.') from exc
        if exc.code == 429:
            raise RuntimeError('Limite diário de consultas de placa atingido.') from exc
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

    plate = only_plate_chars(_first_value(data, 'placa', 'PLACA', 'plate')) or fallback_plate
    description_parts = [
        _first_value(data, 'marca', 'MARCA', 'marcaModelo', 'brand'),
        _first_value(data, 'modelo', 'MODELO', 'model'),
        _first_value(data, 'submodelo', 'SUBMODELO', 'versao', 'VERSAO', 'version'),
        _first_value(data, 'anoModelo', 'ano_modelo', 'ano', 'model_year', 'year'),
        _first_value(data, 'cor', 'COR', 'color'),
    ]
    vehicle_description = ' '.join(part for part in description_parts if part).upper()

    extra = payload.get('extra') if isinstance(payload.get('extra'), dict) else data.get('extra')
    extra = extra if isinstance(extra, dict) else {}

    def field(*keys):
        return _first_value(data, *keys) or _first_value(extra, *keys)

    chassi = field('chassi', 'CHASSI')
    details = {
        'marca': field('MARCA', 'marca', 'brand'),
        'modelo': field('MODELO', 'modelo', 'model'),
        'versao': field('VERSAO', 'versao', 'SUBMODELO', 'submodelo'),
        'ano_fabricacao': field('ano', 'ano_fabricacao', 'anoFabricacao'),
        'ano_modelo': field('anoModelo', 'ano_modelo'),
        'cor': field('cor', 'COR', 'color'),
        'combustivel': field('combustivel', 'COMBUSTIVEL'),
        'cilindradas': field('cilindradas', 'cilindrada'),
        'potencia': field('potencia', 'POTENCIA'),
        'tipo': field('tipo_veiculo', 'tipo', 'segmento'),
        'passageiros': field('quantidade_passageiro', 'passageiros'),
        'nacionalidade': field('nacionalidade'),
        'municipio': field('municipio', 'MUNICIPIO'),
        'uf': field('uf', 'UF'),
        'situacao': field('situacao', 'SITUACAO', 'situacao_veiculo'),
        'chassi_final': chassi[-4:] if len(chassi) >= 4 else '',  # só o final: o resto vem mascarado ou não interessa à oficina
    }
    situation = details['situacao'].lower()
    return {
        'placa': plate,
        'veiculo_descricao': vehicle_description,
        'detalhes': {key: value for key, value in details.items() if value},
        'alerta_roubo': any(word in situation for word in ('roubo', 'furto')),
        'fipe': _best_fipe(payload.get('fipe')),
    }


def _best_fipe(fipe) -> dict | None:
    """Escolhe a entrada FIPE de maior pontuação (a API pode devolver várias versões)."""
    rows = fipe.get('dados') if isinstance(fipe, dict) else fipe
    rows = [row for row in rows or [] if isinstance(row, dict) and row.get('texto_valor')]
    if not rows:
        return None
    best = max(rows, key=lambda row: float(row.get('score') or 0))
    return {'valor': best.get('texto_valor'), 'modelo': best.get('texto_modelo'), 'codigo': best.get('codigo_fipe'),
            'referencia': best.get('mes_referencia')}


def _first_value(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value not in (None, '', [], {}):
            return str(value).strip()
    return ''
