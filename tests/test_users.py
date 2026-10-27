from types import SimpleNamespace

from starlette.requests import Request

from app import models
from app.database import SessionLocal
from app.routers.users import delete_user
from tests.conftest import ADMIN_PASSWORD
from tests.helpers import csrf_headers, login


def _post(client, path, data=None):
    return client.post(
        path,
        data=data or {},
        headers=csrf_headers(client),
        follow_redirects=False,
    )


def _user(username: str) -> models.User | None:
    db = SessionLocal()
    try:
        return db.query(models.User).filter_by(username=username).first()
    finally:
        db.close()


def _user_id(username: str) -> int:
    db = SessionLocal()
    try:
        return db.query(models.User).filter_by(username=username).one().id
    finally:
        db.close()


def test_create_user_rejects_empty_and_duplicate_username(client):
    login(client, "admin", ADMIN_PASSWORD)

    empty = _post(
        client,
        "/users/create",
        {
            "username": "   ",
            "full_name": "Sin Nombre",
            "password": "ClaveSegura1234",
            "role": "operador",
        },
    )
    assert empty.status_code == 303
    assert "error=" in empty.headers["location"]

    duplicate = _post(
        client,
        "/users/create",
        {
            "username": "admin",
            "full_name": "Admin Duplicado",
            "password": "ClaveSegura1234",
            "role": "operador",
        },
    )
    assert duplicate.status_code == 303
    assert "error=" in duplicate.headers["location"]


def test_create_user_accepts_role_names_and_rejects_invalid_roles(client):
    login(client, "admin", ADMIN_PASSWORD)

    accepted = _post(
        client,
        "/users/create",
        {
            "username": "gestor",
            "full_name": "Gestor Nuevo",
            "password": "ClaveSegura1234",
            "role": "ADMIN",
        },
    )
    assert accepted.status_code == 303
    assert "error=" not in accepted.headers["location"]
    assert _user("gestor").role == models.UserRole.ADMIN

    invalid = _post(
        client,
        "/users/create",
        {
            "username": "fantasma",
            "full_name": "Rol Invalido",
            "password": "ClaveSegura1234",
            "role": "superusuario",
        },
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]
    assert _user("fantasma") is None


def test_update_user_handles_missing_user_and_invalid_role(client):
    login(client, "admin", ADMIN_PASSWORD)

    missing = _post(
        client,
        "/users/update",
        {"user_id": 999999, "full_name": "Nadie", "role": "operador", "password": ""},
    )
    assert missing.status_code == 303
    assert "error=" in missing.headers["location"]

    operator_id = _user_id("operator")
    invalid = _post(
        client,
        "/users/update",
        {"user_id": operator_id, "full_name": "Operador", "role": "superusuario", "password": ""},
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]
    assert _user("operator").role == models.UserRole.OPERATOR


def test_delete_user_blocks_self_and_missing_targets(client):
    login(client, "admin", ADMIN_PASSWORD)
    admin_id = _user_id("admin")

    self_delete = _post(client, f"/users/delete/{admin_id}")
    assert self_delete.status_code == 303
    assert "error=" in self_delete.headers["location"]
    assert _user("admin") is not None

    missing = _post(client, "/users/delete/999999")
    assert missing.status_code == 303
    assert "error=" in missing.headers["location"]


def test_delete_last_active_admin_is_blocked_when_requester_is_not_admin():
    db = SessionLocal()
    try:
        admin = db.query(models.User).filter_by(username="admin").one()
        scope = {
            "type": "http",
            "method": "POST",
            "path": f"/users/delete/{admin.id}",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
            "root_path": "",
        }
        request = Request(scope)
        request.state.user = SimpleNamespace(id=999)

        response = delete_user(admin.id, request, db)

        assert response.status_code == 303
        assert "error=" in response.headers["location"]
        assert db.query(models.User).filter_by(id=admin.id).one().is_active is True
    finally:
        db.close()
