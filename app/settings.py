from __future__ import annotations

from datetime import date, timedelta

from .models import SystemSettings


DEFAULTS = {
    'company_name': 'Japa Auto Center',
    'budget_prefix': 'ORC',
    'work_order_prefix': 'OS',
    'budget_validity_days': 7,
    'warranty_days': 90,
}


def get_system_settings() -> SystemSettings:
    settings = SystemSettings.query.order_by(SystemSettings.id.asc()).first()
    if settings:
        return settings
    return SystemSettings(**DEFAULTS)


def budget_default_date() -> date:
    settings = get_system_settings()
    return date.today() + timedelta(days=max(settings.budget_validity_days or 0, 0))
