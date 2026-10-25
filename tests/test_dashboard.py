from datetime import datetime, time

from app import auth, models
from app.database import SessionLocal
from app.utils.time import today_local
from tests.conftest import USER_PASSWORD
from tests.helpers import csrf_headers, create_student, get_door_id, login

TODAY = today_local().isoformat()


def _create_exit_logs(student_id, door_id, times=(time(8, 15), time(9, 30))):
    db = SessionLocal()
    try:
        operator = db.query(models.User).filter_by(username="operator").one()
        for moment in times:
            db.add(
                models.ExitLog(
                    student_id=student_id,
                    operator_id=operator.id,
                    door_id=door_id,
                    timestamp=datetime.combine(today_local(), moment),
                    student_name="Ana Perez",
                    course="10A",
                    door_name="Puerta Principal",
                    authorized_at_scan=True,
                )
            )
        db.commit()
    finally:
        db.close()


def test_exit_dashboard_stats_charts_and_details(client):
    login(client, "operator", USER_PASSWORD)
    student = create_student()
    door_id = get_door_id()
    _create_exit_logs(student.id, door_id)

    stats = client.get(f"/api/dashboard/stats?date={TODAY}")
    assert stats.status_code == 200
    body = stats.json()
    assert body["exits_count"] == 2
    assert body["total_students"] == 1
    assert body["doors_data"][0]["id"] == door_id
    assert body["doors_data"][0]["count"] == 2
    assert body["doors_data"][0]["percent"] == 100.0

    charts = client.get(f"/api/dashboard/chart-data?date={TODAY}").json()
    assert charts["courses"] == {"labels": ["10A"], "data": [2]}
    assert charts["timeline"] == {"labels": ["8:00", "9:00"], "data": [1, 1]}

    db = SessionLocal()
    try:
        row = db.query(models.Student).filter_by(id=student.id).one()
        row.full_name = "Nombre Editado"
        row.course = "11B"
        db.commit()
    finally:
        db.close()

    details = client.get(f"/api/dashboard/details?type=door&id={door_id}&date={TODAY}").json()
    assert len(details) == 2
    assert {item["name"] for item in details} == {"Ana Perez"}
    assert {item["course"] for item in details} == {"10A"}
    assert {item["door"] for item in details} == {"Puerta Principal"}


def test_lunch_dashboard_stats_charts_and_details(client):
    login(client, "lunch", USER_PASSWORD)
    student = create_student()

    created = client.post(
        "/lunch/process",
        json={"method": "qr", "code": auth.sign_qr_content(student.student_id)},
        headers=csrf_headers(client),
    )
    assert created.status_code == 200
    public_id = created.json()["ticket"]["public_id"]

    stats = client.get(f"/api/dashboard/lunch/stats?date={TODAY}")
    assert stats.status_code == 200
    assert stats.json() == {
        "total": 1,
        "normal": 1,
        "special": 0,
        "by_person": {"students": 1, "employees": 0},
    }

    charts = client.get(f"/api/dashboard/lunch/chart-data?date={TODAY}").json()
    assert charts["distribution"] == {"labels": ["Normal", "Especial"], "data": [1, 0]}
    assert charts["timeline"]["data"] == [1]

    db = SessionLocal()
    try:
        row = db.query(models.Student).filter_by(id=student.id).one()
        row.full_name = "Nombre Editado"
        row.course = "11B"
        db.commit()
    finally:
        db.close()

    details = client.get(f"/api/dashboard/lunch/details?type=Normal&date={TODAY}").json()
    assert len(details) == 1
    item = details[0]
    assert item["name"] == "Ana Perez"
    assert item["extra"] == "10A"
    assert item["type"] == "Normal"
    assert item["public_id"] == public_id
    assert item["photo"] is None
    assert client.get(f"/api/dashboard/lunch/details?type=Especial&date={TODAY}").json() == []
