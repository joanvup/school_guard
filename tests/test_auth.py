from app import models
from app.database import SessionLocal
from tests.conftest import USER_PASSWORD
from tests.helpers import csrf_token, login


def test_login_success_sets_cookie(client):
    response, _ = login(client, "operator", USER_PASSWORD)
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/dashboard"
    assert client.cookies.get("access_token")
    assert client.get("/scan/").status_code == 200


def test_wrong_password_is_generic_and_rejected(client):
    response, _ = login(client, "operator", "incorrecta")
    assert response.status_code == 401
    assert "Usuario o contraseña incorrectos" in response.text
    assert client.cookies.get("access_token") is None


def test_inactive_user_cannot_login(client):
    response, _ = login(client, "inactive", USER_PASSWORD)
    assert response.status_code == 401
    assert client.cookies.get("access_token") is None


def test_lockout_after_five_failures(client):
    for _ in range(5):
        response, _ = login(client, "operator", "incorrecta")
        assert response.status_code == 401

    blocked, _ = login(client, "operator", "incorrecta")
    assert blocked.status_code == 429


def test_changing_token_version_invalidates_existing_session(client):
    login(client, "operator", USER_PASSWORD)
    assert client.get("/scan/").status_code == 200

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="operator").one()
        user.token_version = (user.token_version or 0) + 1
        db.commit()
    finally:
        db.close()

    assert client.get("/scan/").status_code == 401


def test_logout_requires_csrf_and_clears_session(client):
    login(client, "operator", USER_PASSWORD)
    token = csrf_token(client)

    without_token = client.post("/logout", follow_redirects=False)
    assert without_token.status_code == 403

    response = client.post(
        "/logout",
        headers={"X-CSRF-Token": token},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert client.get("/scan/").status_code == 401
