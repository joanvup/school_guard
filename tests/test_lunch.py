from app import auth, models
from app.database import SessionLocal
from app.utils.time import today_local
from tests.conftest import USER_PASSWORD
from tests.helpers import csrf_headers, create_employee, create_student, login


def _process(client, code):
    return client.post(
        "/lunch/process",
        json={"code": code},
        headers=csrf_headers(client),
    )


def test_signed_qr_records_daily_lunch(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student()

    response = _process(client, auth.sign_qr_content(student.student_id))
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["lunch_type"] == "Normal"

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
    finally:
        db.close()


def test_duplicate_lunch_is_reported_without_new_row(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student()

    assert _process(client, auth.sign_qr_content(student.student_id)).json()["status"] == "success"
    duplicate = _process(client, auth.sign_qr_content(student.student_id))
    assert duplicate.json()["status"] == "warning"

    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).filter_by(student_id=student.id).count() == 1
    finally:
        db.close()


def test_employee_qr_is_supported(client):
    login(client, "lunch", USER_PASSWORD)
    employee = create_employee()

    response = _process(client, auth.sign_qr_content(employee.doc_id))
    assert response.json()["status"] == "success"

    db = SessionLocal()
    try:
        log = db.query(models.LunchLog).one()
        assert log.employee_id == employee.id
        assert log.person_extra == "Profesor"
    finally:
        db.close()


def test_inactive_or_unsubscribed_people_are_denied(client):
    login(client, "lunch", USER_PASSWORD)
    inactive = create_student(student_id="S300", is_active=False)
    without_lunch = create_student(student_id="S301", has_lunch=False)

    assert _process(client, auth.sign_qr_content(inactive.student_id)).json()["status"] == "denied"
    assert (
        _process(client, auth.sign_qr_content(without_lunch.student_id)).json()["status"]
        == "denied"
    )

    db = SessionLocal()
    try:
        assert db.query(models.LunchLog).count() == 0
    finally:
        db.close()
