"""Chave da landing (website/app.py) em produção sem LANDING_SECRET_KEY no .env."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('lshub_landing_app_test', ROOT / 'website' / 'app.py')
landing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(landing)


@pytest.fixture(autouse=True)
def no_configured_key(monkeypatch):
    monkeypatch.delenv('LANDING_SECRET_KEY', raising=False)
    monkeypatch.delenv('SECRET_KEY', raising=False)


def test_production_key_is_created_once_and_shared(tmp_path):
    key_file = tmp_path / 'website' / 'landing_secret_key'
    first = landing.landing_secret_key('production', key_file)
    assert len(first) == 64
    assert landing.landing_secret_key('production', key_file) == first


def test_short_configured_key_is_still_rejected_in_production(tmp_path, monkeypatch):
    monkeypatch.setenv('LANDING_SECRET_KEY', 'curta')
    with pytest.raises(RuntimeError):
        landing.landing_secret_key('production', tmp_path / 'k')


def test_development_never_writes_a_key_file(tmp_path):
    landing.landing_secret_key('development', tmp_path / 'k')
    assert not (tmp_path / 'k').exists()
