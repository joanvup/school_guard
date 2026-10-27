import pytest

from app import auth, models
from app.config import settings
from app.database import SessionLocal
from tests.conftest import ADMIN_PASSWORD
from tests.helpers import csrf_headers, login


@pytest.mark.parametrize(
    "password",
    [
        "Corta1",
        "sinNumerosSuficientes",
        "1234567890123",
        "aaaaaaaaaaaa1",
        "password1234",
        "ClaveDelUsuario123",
    ],
)
def test_weak_passwords_are_rejected(password):
    with pytest.raises(ValueError):
        auth.validate_password(password, username="usuario")


def test_strong_password_is_accepted():
    auth.validate_password("ClaveSegura1234", username="usuario")


def test_password_too_long_is_rejected():
    with pytest.raises(ValueError):
        auth.validate_password("A1" * 100, username="usuario")


def test_create_user_rejects_weak_password(client):
    login(client, "admin", ADMIN_PASSWORD)

    response = client.post(
        "/users/create",
        data={
            "username": "debil",
            "full_name": "Clave Débil",
            "password": "corta1",
            "role": "operador",
        },
        headers=csrf_headers(client),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db = SessionLocal()
    try:
        assert db.query(models.User).filter_by(username="debil").first() is None
    finally:
        db.close()


def test_update_user_rejects_weak_password_without_touching_session(client):
    login(client, "admin", ADMIN_PASSWORD)

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="operator").one()
        original_hash = user.hashed_password
        user_id = user.id
    finally:
        db.close()

    response = client.post(
        "/users/update",
        data={
            "user_id": user_id,
            "full_name": "Operador",
            "role": "operador",
            "password": "abc123",
        },
        headers=csrf_headers(client),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(id=user_id).one()
        assert user.hashed_password == original_hash
        assert user.token_version == 0
    finally:
        db.close()


def test_minimum_length_comes_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "password_min_length", 16)
    with pytest.raises(ValueError):
        auth.validate_password("ClaveSegura1234")
    auth.validate_password("ClaveSegura123456")
