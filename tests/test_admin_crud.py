from datetime import date, datetime, timezone

from app import auth, models
from app.database import SessionLocal
from tests.conftest import ADMIN_PASSWORD
from tests.helpers import create_student, csrf_headers, get_door_id, login


def _admin_post(client, path, data):
    return client.post(
        path,
        data=data,
        headers=csrf_headers(client),
        follow_redirects=False,
    )


def _admin_id() -> int:
    db = SessionLocal()
    try:
        return db.query(models.User).filter_by(username="admin").one().id
    finally:
        db.close()


def _audit_actions() -> list[str]:
    db = SessionLocal()
    try:
        return [row.action for row in db.query(models.AuditLog).all()]
    finally:
        db.close()


def test_student_without_history_is_deleted_and_audited(client):
    login(client, "admin", ADMIN_PASSWORD)
    student = create_student(student_id="S900")

    response = _admin_post(client, f"/students/delete/{student.id}", {})

    assert response.status_code == 303
    db = SessionLocal()
    try:
        assert db.query(models.Student).filter_by(id=student.id).first() is None
    finally:
        db.close()
    assert "student.deleted" in _audit_actions()


def test_student_with_lunch_history_is_deactivated(client):
    login(client, "admin", ADMIN_PASSWORD)
    student = create_student(student_id="S901")

    db = SessionLocal()
    try:
        db.add(
            models.LunchLog(
                service_date=date.today(),
                student_id=student.id,
                operator_id=_admin_id(),
                timestamp=datetime.now(timezone.utc),
                delivered_type="Normal",
            )
        )
        db.commit()
    finally:
        db.close()

    response = _admin_post(client, f"/students/delete/{student.id}", {})

    assert response.status_code == 303
    db = SessionLocal()
    try:
        row = db.query(models.Student).filter_by(id=student.id).one()
        assert row.is_active is False
    finally:
        db.close()
    assert "student.deactivated" in _audit_actions()


def test_door_without_history_is_deleted_and_audited(client):
    login(client, "admin", ADMIN_PASSWORD)

    db = SessionLocal()
    try:
        door = models.Door(name="Puerta Temporal", is_active=True)
        db.add(door)
        db.commit()
        door_id = door.id
    finally:
        db.close()

    response = _admin_post(client, f"/doors/delete/{door_id}", {})

    assert response.status_code == 303
    db = SessionLocal()
    try:
        assert db.query(models.Door).filter_by(id=door_id).first() is None
    finally:
        db.close()
    assert "door.deleted" in _audit_actions()


def test_door_with_exit_history_is_deactivated(client):
    login(client, "admin", ADMIN_PASSWORD)
    student = create_student(student_id="S902")

    db = SessionLocal()
    try:
        door = models.Door(name="Puerta Histórica", is_active=True)
        db.add(door)
        db.flush()
        db.add(
            models.ExitLog(
                student_id=student.id,
                operator_id=_admin_id(),
                door_id=door.id,
                timestamp=datetime.now(timezone.utc),
            )
        )
        db.commit()
        door_id = door.id
    finally:
        db.close()

    response = _admin_post(client, f"/doors/delete/{door_id}", {})

    assert response.status_code == 303
    db = SessionLocal()
    try:
        row = db.query(models.Door).filter_by(id=door_id).one()
        assert row.is_active is False
    finally:
        db.close()
    assert "door.deactivated" in _audit_actions()


def test_last_active_door_cannot_be_deleted(client):
    login(client, "admin", ADMIN_PASSWORD)
    door_id = get_door_id()

    response = _admin_post(client, f"/doors/delete/{door_id}", {})

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db = SessionLocal()
    try:
        assert db.query(models.Door).filter_by(id=door_id).one().is_active is True
    finally:
        db.close()


def test_user_without_history_is_deleted_and_audited(client):
    login(client, "admin", ADMIN_PASSWORD)

    db = SessionLocal()
    try:
        user_id = db.query(models.User).filter_by(username="lunch").one().id
    finally:
        db.close()

    response = _admin_post(client, f"/users/delete/{user_id}", {})

    assert response.status_code == 303
    db = SessionLocal()
    try:
        assert db.query(models.User).filter_by(id=user_id).first() is None
    finally:
        db.close()
    assert "user.deleted" in _audit_actions()


def test_user_with_audit_history_is_deactivated_and_tokens_are_invalidated(client):
    login(client, "admin", ADMIN_PASSWORD)

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="operator").one()
        db.add(models.AuditLog(actor_id=user.id, action="legacy.action"))
        db.commit()
        user_id = user.id
    finally:
        db.close()

    response = _admin_post(client, f"/users/delete/{user_id}", {})

    assert response.status_code == 303
    db = SessionLocal()
    try:
        row = db.query(models.User).filter_by(id=user_id).one()
        assert row.is_active is False
        assert row.token_version == 1
    finally:
        db.close()
    assert "user.deactivated" in _audit_actions()


def test_user_creation_role_change_and_password_reset_are_audited(client):
    login(client, "admin", ADMIN_PASSWORD)

    create_response = _admin_post(
        client,
        "/users/create",
        {
            "username": "nuevo",
            "full_name": "Nuevo Operador",
            "password": "ClaveSegura1234",
            "role": "operador",
        },
    )
    assert create_response.status_code == 303
    assert "error=" not in create_response.headers["location"]

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="nuevo").one()
        assert user.role == models.UserRole.OPERATOR
        assert user.token_version == 0
        user_id = user.id
    finally:
        db.close()

    role_response = _admin_post(
        client,
        "/users/update",
        {
            "user_id": user_id,
            "full_name": "Nuevo Operador",
            "role": "operador_almuerzo",
            "password": "",
        },
    )
    assert role_response.status_code == 303
    assert "error=" not in role_response.headers["location"]

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(id=user_id).one()
        assert user.role == models.UserRole.LUNCH_OP
        assert user.token_version == 1
    finally:
        db.close()

    password_response = _admin_post(
        client,
        "/users/update",
        {
            "user_id": user_id,
            "full_name": "Nuevo Operador",
            "role": "operador_almuerzo",
            "password": "OtraClaveSegura5678",
        },
    )
    assert password_response.status_code == 303
    assert "error=" not in password_response.headers["location"]

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(id=user_id).one()
        assert user.token_version == 2
        assert auth.verify_password("OtraClaveSegura5678", user.hashed_password)
    finally:
        db.close()

    actions = _audit_actions()
    assert actions.count("user.created") == 1
    assert actions.count("user.updated") == 2


def test_last_admin_cannot_be_demoted(client):
    login(client, "admin", ADMIN_PASSWORD)
    admin_id = _admin_id()

    response = _admin_post(
        client,
        "/users/update",
        {
            "user_id": admin_id,
            "full_name": "Admin",
            "role": "operador",
            "password": "",
        },
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db = SessionLocal()
    try:
        assert db.query(models.User).filter_by(id=admin_id).one().role == models.UserRole.ADMIN
    finally:
        db.close()
