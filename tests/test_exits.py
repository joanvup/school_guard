from sqlalchemy.orm import Session

from app import auth, models
from app.database import SessionLocal
from app.services.qr import sign_qr_v2
from tests.conftest import USER_PASSWORD
from tests.helpers import csrf_headers, create_employee, create_student, get_door_id, login


def _first_commit_raises(monkeypatch, error: Exception):
    original = Session.commit
    calls = {"count": 0}

    def flaky_commit(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise error
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Session, "commit", flaky_commit)


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

    first = _scan(client, unauthorized)
    second = _scan(client, inactive)
    assert first.status_code == 403
    assert first.json()["status"] == "denied"
    assert second.status_code == 403
    assert second.json()["status"] == "denied"

    db = SessionLocal()
    try:
        assert db.query(models.ExitLog).count() == 0
        results = {row.result for row in db.query(models.ScanAttempt).all()}
        assert results == {"denied"}
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


def test_forged_qr_is_rejected_and_audited(client):
    login(client, "operator", USER_PASSWORD)
    student = create_student()

    response = _scan(client, student, code=f"{student.student_id}.{'0' * 16}")
    assert response.status_code == 403
    assert response.json()["status"] == "denied"

    db = SessionLocal()
    try:
        attempt = db.query(models.ScanAttempt).one()
        assert attempt.result == "invalid_signature"
        assert attempt.code_hash != f"{student.student_id}.{'0' * 16}"
        assert db.query(models.ExitLog).count() == 0
    finally:
        db.close()


def test_v2_student_card_is_accepted(client):
    login(client, "operator", USER_PASSWORD)
    student = create_student(student_id="S202")

    response = _scan(client, student, code=sign_qr_v2("student", student.student_id))
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_v2_employee_card_cannot_register_an_exit(client):
    login(client, "operator", USER_PASSWORD)
    employee = create_employee(doc_id="E202")

    response = _scan(client, employee, code=sign_qr_v2("employee", employee.doc_id))
    assert response.status_code == 403
    assert response.json()["status"] == "denied"

    db = SessionLocal()
    try:
        assert db.query(models.ExitLog).count() == 0
        assert db.query(models.ScanAttempt).one().result == "denied"
    finally:
        db.close()


def test_unknown_signed_id_is_denied_and_audited(client):
    login(client, "operator", USER_PASSWORD)

    response = client.post(
        "/scan/process",
        json={"qr_code": auth.sign_qr_content("S999"), "door_id": get_door_id()},
        headers=csrf_headers(client),
    )
    assert response.status_code == 403
    assert response.json()["status"] == "denied"

    db = SessionLocal()
    try:
        assert db.query(models.ScanAttempt).one().result == "unknown_person"
    finally:
        db.close()


def test_cooldown_returns_conflict_and_records_duplicate(client):
    login(client, "operator", USER_PASSWORD)
    student = create_student()

    assert _scan(client, student).json()["status"] == "success"
    second = _scan(client, student)
    assert second.status_code == 409
    assert second.json()["status"] == "warning"
    assert second.json()["previous_timestamp"]

    db = SessionLocal()
    try:
        assert db.query(models.ExitLog).count() == 1
        assert db.query(models.ScanAttempt).filter_by(result="duplicate").count() == 1
    finally:
        db.close()


def test_scan_attempt_records_every_result(client):
    login(client, "operator", USER_PASSWORD)
    student = create_student()
    unauthorized = create_student(student_id="S203", is_authorized=False)

    _scan(client, student)
    _scan(client, student)
    _scan(client, unauthorized)
    _scan(client, student, code="forged.0000000000000000")

    db = SessionLocal()
    try:
        results = [row.result for row in db.query(models.ScanAttempt).all()]
        assert sorted(results) == ["denied", "duplicate", "invalid_signature", "success"]
        assert all(row.code_hash for row in db.query(models.ScanAttempt).all())
    finally:
        db.close()


def test_invalid_scan_payload_returns_422(client):
    login(client, "operator", USER_PASSWORD)
    student = create_student()

    empty = client.post(
        "/scan/process",
        json={"qr_code": "   ", "door_id": get_door_id()},
        headers=csrf_headers(client),
    )
    invalid_door = _scan(client, student, door_id="abc")
    missing_door = client.post(
        "/scan/process",
        json={"qr_code": auth.sign_qr_content(student.student_id)},
        headers=csrf_headers(client),
    )

    assert empty.status_code == 422
    assert invalid_door.status_code == 422
    assert missing_door.status_code == 422


def test_commit_error_is_reported_and_audited(client, monkeypatch):
    login(client, "operator", USER_PASSWORD)
    student = create_student(student_id="S204")
    _first_commit_raises(monkeypatch, RuntimeError("fallo de escritura"))

    response = _scan(client, student)

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "ERROR INTERNO AL REGISTRAR LA SALIDA"

    db = SessionLocal()
    try:
        assert db.query(models.ExitLog).count() == 0
        assert db.query(models.ScanAttempt).filter_by(result="error").count() == 1
    finally:
        db.close()
