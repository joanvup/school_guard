from app import auth, models
from app.database import SessionLocal
from tests.conftest import USER_PASSWORD
from tests.helpers import csrf_headers, create_student, get_door_id, login


def _scan(client, student, door_id=None, code=None):
    return client.post(
        "/scan/process",
        json={
            "qr_code": code or auth.sign_qr_content(student.student_id),
            "door_id": door_id if door_id is not None else get_door_id(),
        },
        headers=csrf_headers(client),
    )


def test_authorized_exit_records_and_freezes_snapshot(client):
    login(client, "operator", USER_PASSWORD)
    student = create_student()

    response = _scan(client, student)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    db = SessionLocal()
    try:
        log = db.query(models.ExitLog).one()
        assert log.student_name == "Ana Perez"
        assert log.course == "10A"
        assert log.door_name == "Puerta Principal"
        assert log.authorized_at_scan is True

        student_row = db.query(models.Student).filter_by(id=student.id).one()
        student_row.full_name = "Nombre Editado"
        student_row.course = "11B"
        db.commit()

        db.refresh(log)
        assert log.student_name == "Ana Perez"
        assert log.course == "10A"
    finally:
        db.close()


def test_unauthorized_and_inactive_students_are_denied(client):
    login(client, "operator", USER_PASSWORD)
    unauthorized = create_student(student_id="S200", is_authorized=False)
    inactive = create_student(student_id="S201", is_active=False)

    assert _scan(client, unauthorized).json()["status"] == "denied"
    assert _scan(client, inactive).json()["status"] == "denied"

    db = SessionLocal()
    try:
        assert db.query(models.ExitLog).count() == 0
    finally:
        db.close()


def test_inactive_door_is_rejected(client):
    login(client, "operator", USER_PASSWORD)
    student = create_student()

    db = SessionLocal()
    try:
        door = models.Door(name="Puerta Cerrada", is_active=False)
        db.add(door)
        db.commit()
        door_id = door.id
    finally:
        db.close()

    response = _scan(client, student, door_id=door_id)
    assert response.status_code == 403
    assert response.json()["status"] == "denied"


def test_forged_qr_is_rejected(client):
    login(client, "operator", USER_PASSWORD)
    student = create_student()

    response = _scan(client, student, code=f"{student.student_id}.{'0' * 16}")
    assert response.json()["status"] == "denied"


def test_cooldown_prevents_duplicate_exit(client):
    login(client, "operator", USER_PASSWORD)
    student = create_student()

    assert _scan(client, student).json()["status"] == "success"
    second = _scan(client, student)
    assert second.json()["status"] == "warning"

    db = SessionLocal()
    try:
        assert db.query(models.ExitLog).count() == 1
    finally:
        db.close()

    invalid_door = _scan(client, student, door_id="abc")
    assert invalid_door.status_code == 400
