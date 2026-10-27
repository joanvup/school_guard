from jose import jwt

from app import models
from app.config import settings
from app.database import SessionLocal
from tests.conftest import ADMIN_PASSWORD, USER_PASSWORD
from tests.helpers import login


def _token(**claims):
    return jwt.encode(claims, settings.secret_key, algorithm=settings.algorithm)


def _set_cookie(client, value):
    client.cookies.set("access_token", value)


def test_requests_without_cookie_are_rejected(client):
    assert client.get("/lunch/scan").status_code == 401
    assert client.get("/scan/").status_code == 401


def test_non_bearer_scheme_is_rejected(client):
    _set_cookie(client, "Basic abc")
    assert client.get("/lunch/scan").status_code == 401


def test_bearer_without_token_is_rejected(client):
    _set_cookie(client, "Bearer ")
    assert client.get("/lunch/scan").status_code == 401


def test_token_without_subject_is_rejected(client):
    _set_cookie(client, f"Bearer {_token(ver=0)}")
    assert client.get("/lunch/scan").status_code == 401


def test_malformed_token_is_rejected(client):
    _set_cookie(client, "Bearer not-a-jwt")
    assert client.get("/lunch/scan").status_code == 401


def test_token_for_unknown_user_is_rejected(client):
    _set_cookie(client, f"Bearer {_token(sub='ghost', ver=0)}")
    assert client.get("/lunch/scan").status_code == 401


def test_inactive_user_is_rejected(client):
    _set_cookie(client, f"Bearer {_token(sub='inactive', ver=0)}")
    assert client.get("/lunch/scan").status_code == 401


def test_outdated_token_version_is_rejected(client):
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == "lunch").one()
        version = (user.token_version or 0) + 1
    finally:
        db.close()

    _set_cookie(client, f"Bearer {_token(sub='lunch', ver=version)}")
    assert client.get("/lunch/scan").status_code == 401


def test_valid_token_grants_access(client):
    login(client, "lunch", USER_PASSWORD)
    assert client.get("/lunch/scan").status_code == 200


def test_operator_cannot_access_lunch_or_admin_modules(client):
    login(client, "operator", USER_PASSWORD)
    assert client.get("/lunch/scan").status_code == 403
    assert client.get("/employees/").status_code == 403


def test_lunch_operator_cannot_access_exit_or_admin_modules(client):
    login(client, "lunch", USER_PASSWORD)
    assert client.get("/scan/").status_code == 403
    assert client.get("/employees/").status_code == 403


def test_admin_can_access_every_module(client):
    login(client, "admin", ADMIN_PASSWORD)
    assert client.get("/lunch/scan").status_code == 200
    assert client.get("/scan/").status_code == 200
    assert client.get("/employees/").status_code == 200
