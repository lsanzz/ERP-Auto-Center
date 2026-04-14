from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def parse_decimal(value, default: Decimal | float | int = Decimal('0')) -> Decimal:
    if value in (None, ''):
        return Decimal(str(default))
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace('.', '').replace(',', '.') if isinstance(value, str) and ',' in str(value) else str(value).strip()
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal(str(default))


def parse_int(value, default: int | None = None) -> int | None:
    if value in (None, ''):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_date(value) -> date | None:
    if value in (None, ''):
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), '%Y-%m-%d').date()


def format_currency(value) -> str:
    value = parse_decimal(value)
    formatted = f'{value:,.2f}'
    formatted = formatted.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'R$ {formatted}'


def date_br(value) -> str:
    if not value:
        return '-'
    if isinstance(value, str):
        try:
            value = parse_date(value)
        except ValueError:
            return value
    return value.strftime('%d/%m/%Y')


def datetime_br(value) -> str:
    if not value:
        return '-'
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime('%d/%m/%Y %H:%M')


def iso_today() -> str:
    return date.today().isoformat()
