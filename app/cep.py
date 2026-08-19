from __future__ import annotations

from urllib.error import HTTPError, URLError

from .cnpj import _read_json, only_digits


def lookup_cep(cep: str | None) -> dict:
    """Consulta um CEP no ViaCEP e devolve a resposta normalizada pela API."""
    digits = only_digits(cep)
    if len(digits) != 8:
        raise ValueError('Informe um CEP com 8 dígitos.')

    try:
        payload = _read_json(f'https://viacep.com.br/ws/{digits}/json/')
    except HTTPError as exc:
        if exc.code == 400:
            raise ValueError('CEP inválido. Informe 8 dígitos.') from exc
        raise RuntimeError('Falha ao consultar o serviço de CEP.') from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError('Serviço de consulta de CEP indisponível.') from exc

    if not isinstance(payload, dict) or payload.get('erro'):
        raise LookupError('CEP não encontrado.')
    return payload
