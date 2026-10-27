import pytest
from pydantic import ValidationError

from app.config import Settings

VALID = {
    "DATABASE_URL": "sqlite:///config-test.db",
    "SECRET_KEY": "config-test-secret",
    "QR_SECRET_KEY_CURRENT": "config-test-qr-current",
}


def _settings(**overrides):
    return Settings(_env_file=None, **{**VALID, **overrides})


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"DATABASE_URL": "   "}, "DATABASE_URL no puede estar vacío"),
        ({"SECRET_KEY": ""}, "SECRET_KEY es obligatorio"),
        ({"QR_SECRET_KEY_CURRENT": ""}, "QR_SECRET_KEY_CURRENT es obligatorio"),
        ({"ALGORITHM": "HS512"}, "ALGORITHM debe ser HS256"),
        ({"LUNCH_WINDOW_START": "25:00"}, "La ventana de almuerzo debe usar HH:MM"),
        ({"LUNCH_WINDOW_END": "mediodía"}, "La ventana de almuerzo debe usar HH:MM"),
        (
            {"QR_SECRET_KEY_CURRENT": "misma-clave", "QR_SECRET_KEY_PREVIOUS": "misma-clave"},
            "QR_SECRET_KEY_PREVIOUS debe ser distinta de QR_SECRET_KEY_CURRENT",
        ),
        (
            {"LUNCH_WINDOW_START": "14:00", "LUNCH_WINDOW_END": "14:00"},
            "LUNCH_WINDOW_START debe ser anterior a LUNCH_WINDOW_END",
        ),
    ],
)
def test_invalid_settings_are_rejected(overrides, message):
    with pytest.raises(ValidationError, match=message):
        _settings(**overrides)


def test_cookie_secure_defaults_to_app_env(monkeypatch):
    monkeypatch.delenv("COOKIE_SECURE", raising=False)

    assert _settings(APP_ENV="production").cookie_secure_effective is True
    assert _settings(APP_ENV="development").cookie_secure_effective is False


def test_cookie_secure_explicit_value_wins():
    settings = _settings(APP_ENV="production", COOKIE_SECURE="false")

    assert settings.cookie_secure_effective is False
