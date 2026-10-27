from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import SessionLocal
from app.services import lunch as lunch_service
from app.services.qr import sign_qr_v1, sign_qr_v2
from tests.conftest import USER_PASSWORD
from tests.helpers import create_employee, create_student, csrf_headers, login


def _process(client, **payload):
    return client.post("/lunch/process", json=payload, headers=csrf_headers(client))


def _second_commit_raises(monkeypatch, error: Exception):
    original = Session.commit
    calls = {"count": 0}

    def flaky_commit(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise error
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Session, "commit", flaky_commit)


def test_v2_student_qr_is_accepted(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S910")

    response = _process(client, method="qr", code=sign_qr_v2("student", student.student_id))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["person"]["type"] == "Estudiante"

    db = SessionLocal()
    try:
        log = db.query(models.LunchLog).one()
        assert log.student_id == student.id
        assert log.employee_id is None
    finally:
        db.close()


def test_v1_qr_falls_back_to_employee_lookup(client):
    login(client, "lunch", USER_PASSWORD)
    employee = create_employee(doc_id="E910")

    response = _process(client, method="qr", code=sign_qr_v1(employee.doc_id))

    assert response.status_code == 200
    db = SessionLocal()
    try:
        log = db.query(models.LunchLog).one()
        assert log.employee_id == employee.id
        assert log.student_id is None
    finally:
        db.close()


def test_v1_qr_can_resolve_a_student(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S914")

    response = _process(client, method="qr", code=sign_qr_v1(student.student_id))

    assert response.status_code == 200
    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).one().student_id == student.id
    finally:
        db.close()


def test_rfid_scan_resolves_student_and_employee(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S915", rfid_code="RFID-S")
    employee = create_employee(doc_id="E915", rfid_code="RFID-E")

    student_response = _process(client, method="rfid", code="RFID-S")
    employee_response = _process(client, method="rfid", code="RFID-E")
    unknown_response = _process(client, method="rfid", code="RFID-X")

    assert student_response.status_code == 200
    assert employee_response.status_code == 200
    assert unknown_response.status_code == 403
    assert unknown_response.json()["message"] == "NO ENCONTRADO O NO REGISTRADO"
    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).filter_by(student_id=student.id).count() == 1
        assert db.query(models.LunchLog).filter_by(employee_id=employee.id).count() == 1
    finally:
        db.close()


def test_manual_selection_can_target_employee(client):
    login(client, "lunch", USER_PASSWORD)
    employee = create_employee(doc_id="E911")

    response = _process(
        client,
        method="manual",
        person_type="employee",
        person_id=employee.id,
    )

    assert response.status_code == 200
    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).one().employee_id == employee.id
    finally:
        db.close()


def test_manual_selection_can_target_student(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S916")

    response = _process(
        client,
        method="manual",
        person_type="student",
        person_id=student.id,
    )

    assert response.status_code == 200
    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).one().student_id == student.id
    finally:
        db.close()


def test_invalid_lunch_plan_is_denied(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S911", has_lunch=True, lunch_type="Vegetariano")

    response = _process(client, method="qr", code=sign_qr_v2("student", student.student_id))

    assert response.status_code == 403
    assert response.json()["message"] == "PLAN DE ALMUERZO INVÁLIDO"
    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).count() == 0
    finally:
        db.close()


def test_invalid_qr_signature_is_denied(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S917")

    response = _process(client, method="qr", code=sign_qr_v2("student", student.student_id) + "0")

    assert response.status_code == 403
    assert response.json()["message"] == "QR FALSIFICADO O INVÁLIDO"
    db = SessionLocal()
    try:
        assert db.query(models.ScanAttempt).filter_by(result="invalid_signature").count() == 1
        assert db.query(models.LunchLog).count() == 0
    finally:
        db.close()


def test_unknown_qr_person_is_denied(client):
    login(client, "lunch", USER_PASSWORD)

    response = _process(client, method="qr", code=sign_qr_v2("student", "S999"))

    assert response.status_code == 403
    assert response.json()["message"] == "NO ENCONTRADO O NO REGISTRADO"


def test_inactive_person_is_denied(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S918", is_active=False)

    response = _process(client, method="qr", code=sign_qr_v2("student", student.student_id))

    assert response.status_code == 403
    assert response.json()["message"] == "PERSONA INACTIVA"


def test_person_without_lunch_is_denied(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S919", has_lunch=False)

    response = _process(client, method="qr", code=sign_qr_v2("student", student.student_id))

    assert response.status_code == 403
    assert response.json()["message"] == "NO TIENE ALMUERZO ASIGNADO"


def test_lunch_outside_window_is_denied_in_strict_mode(client, monkeypatch):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S920")
    monkeypatch.setattr(settings, "lunch_window_start", "00:00")
    monkeypatch.setattr(settings, "lunch_window_end", "00:00")
    monkeypatch.setattr(settings, "lunch_window_enforcement", "deny")

    response = _process(client, method="qr", code=sign_qr_v2("student", student.student_id))

    assert response.status_code == 403
    assert response.json()["message"] == "FUERA DE LA VENTANA DE ALMUERZO"
    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).count() == 0
    finally:
        db.close()


def test_lunch_outside_window_warns_when_configured(client, monkeypatch):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S921")
    monkeypatch.setattr(settings, "lunch_window_start", "00:00")
    monkeypatch.setattr(settings, "lunch_window_end", "00:00")
    monkeypatch.setattr(settings, "lunch_window_enforcement", "warn")

    response = _process(client, method="qr", code=sign_qr_v2("student", student.student_id))

    assert response.status_code == 200
    body = response.json()
    assert body["outside_window"] is True
    assert body["message"].endswith("(FUERA DE VENTANA)")


def test_duplicate_employee_lunch_returns_existing_ticket(client):
    login(client, "lunch", USER_PASSWORD)
    employee = create_employee(doc_id="E912")

    first = _process(client, method="qr", code=sign_qr_v2("employee", employee.doc_id))
    duplicate = _process(client, method="qr", code=sign_qr_v2("employee", employee.doc_id))

    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["status"] == "warning"
    assert duplicate.json()["ticket"]["public_id"] == first.json()["ticket"]["public_id"]

    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).filter_by(employee_id=employee.id).count() == 1
        assert db.query(models.ScanAttempt).filter_by(result="duplicate").count() == 1
    finally:
        db.close()


def test_unexpected_commit_error_is_reported_and_audited(client, monkeypatch):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S912")
    _second_commit_raises(monkeypatch, RuntimeError("fallo de escritura"))

    response = _process(client, method="qr", code=sign_qr_v2("student", student.student_id))

    assert response.status_code == 500
    assert response.json()["status"] == "error"
    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).count() == 0
        assert db.query(models.ScanAttempt).filter_by(result="error").count() == 1
    finally:
        db.close()


def test_integrity_error_without_existing_record_is_reraised(client, monkeypatch):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S913")
    _second_commit_raises(monkeypatch, IntegrityError("INSERT", {}, Exception("duplicado")))

    response = _process(client, method="qr", code=sign_qr_v2("student", student.student_id))

    assert response.status_code == 500
    assert response.json()["status"] == "error"


def test_search_people_ignores_short_terms_and_finds_both_person_types(client):
    login(client, "lunch", USER_PASSWORD)
    create_employee(doc_id="E913", full_name="Ana Empleada", position="Profesora")
    create_student(student_id="S923", full_name="Ana Estudiante", course="11B")

    db = SessionLocal()
    try:
        assert lunch_service.search_people(db, "ab") == []
    finally:
        db.close()

    response = client.get("/lunch/search_person", params={"q": "Ana"})

    assert response.status_code == 200
    results = response.json()
    assert [item["person_type"] for item in results] == ["employee", "student"]
    assert results[0]["type"] == "Empleado"
    assert results[0]["extra"] == "Profesora"
    assert results[1]["type"] == "Estudiante"
    assert results[1]["extra"] == "11B"


def test_reprint_ticket_tracks_printed_count(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S924")
    _process(client, method="qr", code=sign_qr_v2("student", student.student_id))

    db = SessionLocal()
    try:
        log = db.query(models.LunchLog).one()
        operator = db.query(models.User).filter_by(username="lunch").one()

        results = [
            lunch_service.reprint_ticket(db, public_id=log.public_id, operator=operator)
            for _ in range(4)
        ]

        assert [over_limit for _, over_limit in results] == [False, False, False, True]
        assert db.query(models.LunchLog).one().printed_count == 4
        assert lunch_service.get_ticket(db, "inexistente") is None
        assert lunch_service.reprint_ticket(db, public_id="inexistente", operator=operator) is None
    finally:
        db.close()


def test_reprint_ticket_returns_none_for_unknown_ticket(client):
    login(client, "lunch", USER_PASSWORD)

    response = client.post("/lunch/tickets/no-existe/reprint", headers=csrf_headers(client))

    assert response.status_code == 404
