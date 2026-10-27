from app import models
from app.database import SessionLocal
from tests.conftest import ADMIN_PASSWORD
from tests.helpers import csrf_headers, get_door_id, login


def _post(client, path, data=None):
    return client.post(
        path,
        data=data or {},
        headers=csrf_headers(client),
        follow_redirects=False,
    )


def _door(name: str) -> models.Door | None:
    db = SessionLocal()
    try:
        return db.query(models.Door).filter_by(name=name).first()
    finally:
        db.close()


def _audit_rows(action: str) -> list[models.AuditLog]:
    db = SessionLocal()
    try:
        return db.query(models.AuditLog).filter_by(action=action).all()
    finally:
        db.close()


def test_list_doors_renders_for_admin(client):
    login(client, "admin", ADMIN_PASSWORD)

    response = client.get("/doors/")

    assert response.status_code == 200
    assert "Puerta Principal" in response.text


def test_create_door_validates_name_and_duplicates(client):
    login(client, "admin", ADMIN_PASSWORD)

    empty = _post(client, "/doors/create", {"name": "   ", "description": "Sin nombre"})
    assert empty.status_code == 303
    assert "error=" in empty.headers["location"]

    duplicate = _post(client, "/doors/create", {"name": "Puerta Principal"})
    assert duplicate.status_code == 303
    assert "error=" in duplicate.headers["location"]

    created = _post(
        client,
        "/doors/create",
        {"name": "Puerta Secundaria", "description": "Salida lateral"},
    )
    assert created.status_code == 303
    assert "error=" not in created.headers["location"]
    door = _door("Puerta Secundaria")
    assert door is not None
    assert door.description == "Salida lateral"

    audits = _audit_rows("door.created")
    assert len(audits) == 1
    assert audits[0].details == {"name": "Puerta Secundaria"}


def test_delete_missing_door_returns_error(client):
    login(client, "admin", ADMIN_PASSWORD)

    response = _post(client, "/doors/delete/999999")

    assert response.status_code == 303
    assert "error=" in response.headers["location"]


def test_delete_door_with_scan_history_deactivates_it(client):
    login(client, "admin", ADMIN_PASSWORD)

    db = SessionLocal()
    try:
        door = models.Door(name="Puerta Escaneada", is_active=True)
        db.add(door)
        db.flush()
        db.add(models.ScanAttempt(module="exit", method="qr", result="ok", door_id=door.id))
        db.commit()
        door_id = door.id
    finally:
        db.close()

    response = _post(client, f"/doors/delete/{door_id}")

    assert response.status_code == 303
    assert "error=" not in response.headers["location"]
    db = SessionLocal()
    try:
        assert db.query(models.Door).filter_by(id=door_id).one().is_active is False
    finally:
        db.close()
    audits = _audit_rows("door.deactivated")
    assert len(audits) == 1
    assert audits[0].details == {"name": "Puerta Escaneada"}


def test_toggle_missing_door_returns_error(client):
    login(client, "admin", ADMIN_PASSWORD)

    response = _post(client, "/doors/toggle/999999")

    assert response.status_code == 303
    assert "error=" in response.headers["location"]


def test_toggle_last_active_door_is_blocked(client):
    login(client, "admin", ADMIN_PASSWORD)
    door_id = get_door_id()

    response = _post(client, f"/doors/toggle/{door_id}")

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db = SessionLocal()
    try:
        assert db.query(models.Door).filter_by(id=door_id).one().is_active is True
    finally:
        db.close()


def test_toggle_deactivates_and_reactivates_door(client):
    login(client, "admin", ADMIN_PASSWORD)
    door_id = get_door_id()
    _post(client, "/doors/create", {"name": "Puerta Respaldo"})

    deactivated = _post(client, f"/doors/toggle/{door_id}")
    assert deactivated.status_code == 303
    assert "error=" not in deactivated.headers["location"]
    db = SessionLocal()
    try:
        assert db.query(models.Door).filter_by(id=door_id).one().is_active is False
    finally:
        db.close()

    reactivated = _post(client, f"/doors/toggle/{door_id}")
    assert reactivated.status_code == 303
    assert "error=" not in reactivated.headers["location"]
    db = SessionLocal()
    try:
        assert db.query(models.Door).filter_by(id=door_id).one().is_active is True
    finally:
        db.close()

    audits = _audit_rows("door.updated")
    assert len(audits) == 2
    assert audits[0].details["previous_active"] is True
    assert audits[0].details["new_active"] is False
    assert audits[1].details["previous_active"] is False
    assert audits[1].details["new_active"] is True
