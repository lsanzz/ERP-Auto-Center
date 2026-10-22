"""Situação da assinatura desta instalação: ativa, em carência (aviso) ou suspensa (acesso bloqueado)."""
from __future__ import annotations

from datetime import date, timedelta

GRACE_DAYS = 7


def subscription_status(settings, today: date | None = None) -> str:
    if settings is None:
        return 'ATIVA'
    if settings.subscription_suspended:
        return 'SUSPENSA'
    paid_until = settings.subscription_paid_until
    if paid_until is None:
        return 'ATIVA'
    today = today or date.today()
    if today <= paid_until:
        return 'ATIVA'
    return 'CARENCIA' if today <= paid_until + timedelta(days=GRACE_DAYS) else 'SUSPENSA'


def grace_ends(settings) -> date | None:
    if settings is None or settings.subscription_paid_until is None:
        return None
    return settings.subscription_paid_until + timedelta(days=GRACE_DAYS)
