from datetime import datetime

from app import auth, models
from app.config import settings
from app.database import SessionLocal
from app.services import lunch as lunch_service
from app.services.qr import sign_qr_v2
from app.utils.time import LOCAL_TZ, today_local
from tests.conftest import USER_PASSWORD
from tests.helpers import csrf_headers, create_employee, create_student, login


def _process(
    client,
    method="qr",
    code=None,
    person_type=None,
    person_id=None,
):
    payload = {"method": method}
    if code is not None:
        payload["code"] = code
    if person_type is not None:
        payload["person_type"] = person_type
    if person_id is not None:
        payload["person_id"] = person_id

    return client.post("/lunch/process", json=payload, headers=csrf_headers(client))


def test_signed_qr_records_daily_lunch(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student()

    response = _process(client, code=auth.sign_qr_content(student.student_id))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["lunch_type"] == "Normal"
    assert body["ticket"]["public_id"]
    assert body["ticket"]["number"].startswith(f"{today_local():%Y%m%d}-")

    db = SessionLocal()
    try:
        log = db.query(models.LunchLog).one()
        assert log.service_date == today_local()
        assert log.student_id == student.id
        assert log.identification_method == "qr"
        assert log.person_name == "Ana Perez"
        assert log.person_extra == "10A"
        assert log.printed_count == 0
        assert len(log.public_id) == 36
        assert log.public_id == body["ticket"]["public_id"]
    finally:
        db.close()


def test_v2_qr_respects_person_type(client):
    login(client, "lunch", USER_PASSWORD)
    create_student(student_id="X100")
    employee = create_employee(doc_id="X100")

    response = _process(client, code=sign_qr_v2("employee", employee.doc_id))
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    db = SessionLocal()
    try:
        log = db.query(models.LunchLog).one()
        assert log.employee_id == employee.id
        assert log.student_id is None
    finally:
        db.close()


def test_plain_id_and_forged_qr_are_rejected(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S301")

    plain = _process(client, method="qr", code=student.student_id)
    forged = _process(client, method="qr", code=f"{student.student_id}.{'0' * 16}")

    assert plain.status_code == 403
    assert plain.json()["status"] == "denied"
    assert forged.status_code == 403
    assert forged.json()["status"] == "denied"

    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).count() == 0
        assert db.query(models.ScanAttempt).filter_by(result="invalid_signature").count() == 2
    finally:
        db.close()


def test_rfid_only_matches_registered_rfid_code(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S302", rfid_code="RFID-302")

    by_student_id = _process(client, method="rfid", code=student.student_id)
    assert by_student_id.status_code == 403

    by_rfid = _process(client, method="rfid", code="RFID-302")
    assert by_rfid.status_code == 200
    assert by_rfid.json()["status"] == "success"

    db = SessionLocal()
    try:
        log = db.query(models.LunchLog).one()
        assert log.student_id == student.id
        assert log.identification_method == "rfid"
    finally:
        db.close()


def test_manual_selection_requires_type_and_id(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S303")

    missing_id = client.post(
        "/lunch/process",
        json={"method": "manual", "person_type": "student"},
        headers=csrf_headers(client),
    )
    with_code = client.post(
        "/lunch/process",
        json={"method": "manual", "person_type": "student", "code": "algo"},
        headers=csrf_headers(client),
    )
    assert missing_id.status_code == 422
    assert with_code.status_code == 422

    success = _process(client, method="manual", person_type="student", person_id=student.id)
    assert success.status_code == 200

    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).one().identification_method == "manual"
    finally:
        db.close()


def test_duplicate_lunch_returns_existing_ticket(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student()

    first = _process(client, code=auth.sign_qr_content(student.student_id))
    duplicate = _process(client, code=auth.sign_qr_content(student.student_id))

    assert first.status_code == 200
    assert duplicate.status_code == 409
    body = duplicate.json()
    assert body["status"] == "warning"
    assert body["ticket"]["public_id"] == first.json()["ticket"]["public_id"]

    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).filter_by(student_id=student.id).count() == 1
        assert db.query(models.ScanAttempt).filter_by(result="duplicate").count() == 1
    finally:
        db.close()


def test_inactive_or_unsubscribed_people_are_denied(client):
    login(client, "lunch", USER_PASSWORD)
    inactive = create_student(student_id="S300", is_active=False)
    without_lunch = create_student(student_id="S304", has_lunch=False)

    assert _process(client, code=auth.sign_qr_content(inactive.student_id)).status_code == 403
    assert _process(client, code=auth.sign_qr_content(without_lunch.student_id)).status_code == 403

    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).count() == 0
    finally:
        db.close()


def test_ticket_lookup_and_reprint_increment_counter_and_audit(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student()

    created = _process(client, code=auth.sign_qr_content(student.student_id)).json()
    public_id = created["ticket"]["public_id"]

    detail = client.get(f"/lunch/tickets/{public_id}")
    assert detail.status_code == 200
    assert detail.json()["ticket"]["name"] == "Ana Perez"

    printed = client.post(f"/lunch/tickets/{public_id}/reprint", headers=csrf_headers(client))
    assert printed.status_code == 200
    assert printed.json()["printed_count"] == 1
    assert printed.json()["over_limit"] is False
    assert printed.json()["print_url"] == f"/lunch/tickets/{public_id}/print"

    print_view = client.get(f"/lunch/tickets/{public_id}/print")
    assert print_view.status_code == 200
    assert public_id in print_view.text
    assert "setTimeout(() => window.print(), 350)" not in print_view.text

    autoprint_view = client.get(f"/lunch/tickets/{public_id}/print?autoprint=1")
    assert autoprint_view.status_code == 200
    assert "setTimeout(() => window.print(), 350)" in autoprint_view.text
    assert client.get(f"/lunch/tickets/{public_id}/print?autoprint=2").status_code == 422

    db = SessionLocal()
    try:
        log = db.query(models.LunchLog).one()
        assert log.printed_count == 1
        assert log.last_printed_at is not None
        assert db.query(models.AuditLog).filter_by(action="lunch.ticket_reprinted").count() == 1
    finally:
        db.close()

    missing = client.post("/lunch/tickets/no-existe/reprint", headers=csrf_headers(client))
    assert missing.status_code == 404


def test_over_limit_reprint_warns(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student()
    public_id = _process(client, code=auth.sign_qr_content(student.student_id)).json()["ticket"][
        "public_id"
    ]

    last = None
    for _ in range(4):
        last = client.post(f"/lunch/tickets/{public_id}/reprint", headers=csrf_headers(client))
    assert last.json()["printed_count"] == 4
    assert last.json()["over_limit"] is True


def test_lunch_window_can_deny_delivery(client, monkeypatch):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S305")

    monkeypatch.setattr(settings, "lunch_window_enforcement", "deny")
    monkeypatch.setattr(
        lunch_service,
        "now_local",
        lambda: datetime(2026, 1, 1, 15, 0, tzinfo=LOCAL_TZ),
    )

    response = _process(client, code=auth.sign_qr_content(student.student_id))
    assert response.status_code == 403
    assert "VENTANA" in response.json()["message"]

    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).count() == 0
    finally:
        db.close()


def test_lunch_window_warn_mode_records_with_notice(client, monkeypatch):
    login(client, "lunch", USER_PASSWORD)
    student = create_student(student_id="S306")

    monkeypatch.setattr(settings, "lunch_window_enforcement", "warn")
    monkeypatch.setattr(
        lunch_service,
        "now_local",
        lambda: datetime(2026, 1, 1, 15, 0, tzinfo=LOCAL_TZ),
    )

    response = _process(client, code=auth.sign_qr_content(student.student_id))
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["outside_window"] is True
    assert "FUERA DE VENTANA" in response.json()["message"]


def test_search_people_escapes_like_and_hides_scan_codes(client):
    login(client, "lunch", USER_PASSWORD)
    create_student(student_id="S400", full_name="Ana Perez")
    create_student(student_id="S401", full_name="Ana Gomez")
    create_student(student_id="S402", full_name="Inactiva Ana", is_active=False)

    response = client.get("/lunch/search_person?q=Ana")
    assert response.status_code == 200
    results = response.json()
    assert {item["name"] for item in results} == {"Ana Perez", "Ana Gomez"}
    assert all("code" not in item for item in results)
    assert all("person_id" in item and "person_type" in item for item in results)

    escaped = client.get("/lunch/search_person?q=%25%25%25")
    assert escaped.status_code == 200
    assert escaped.json() == []


def test_manual_search_with_invalid_query_is_rejected(client):
    login(client, "lunch", USER_PASSWORD)

    assert client.get("/lunch/search_person?q=ab").status_code == 422
    assert client.get("/lunch/search_person?q=%25").status_code == 422


def test_lunch_process_requires_lunch_role(client):
    login(client, "operator", USER_PASSWORD)
    student = create_student()

    response = _process(client, code=auth.sign_qr_content(student.student_id))
    assert response.status_code == 403


def test_unauthenticated_lunch_process_is_rejected(client):
    response = client.post(
        "/lunch/process",
        json={"method": "qr", "code": "algo"},
        headers={"X-CSRF-Token": "inventado"},
    )
    assert response.status_code in (401, 403)


def test_tickets_are_not_accessible_without_lunch_role(client):
    login(client, "operator", USER_PASSWORD)

    assert client.get("/lunch/tickets/cualquiera").status_code == 403
    assert (
        client.post("/lunch/tickets/cualquiera/reprint", headers=csrf_headers(client)).status_code
        == 403
    )
