import re

from app import models
from app.database import SessionLocal

CSRF_META = re.compile(r'name="csrf-token" content="([^"]+)"')
CSRF_INPUT = re.compile(r'name="csrf_token" value="([^"]+)"')


def csrf_token(client) -> str:
    response = client.get("/")
    match = CSRF_META.search(response.text) or CSRF_INPUT.search(response.text)
    assert match is not None, "La página no expone el token CSRF"
    return match.group(1)


def login(client, username: str, password: str, follow_redirects: bool = False):
    token = csrf_token(client)
    response = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=follow_redirects,
    )
    return response, token


def csrf_headers(client) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token, "No hay cookie CSRF"
    return {"X-CSRF-Token": token}


def create_student(**overrides):
    data = {
        "student_id": "S100",
        "full_name": "Ana Perez",
        "course": "10A",
        "is_authorized": True,
        "is_active": True,
        "has_lunch": True,
        "lunch_type": "Normal",
    }
    data.update(overrides)

    db = SessionLocal()
    try:
        student = models.Student(**data)
        db.add(student)
        db.commit()
        db.refresh(student)
        return student
    finally:
        db.close()


def create_employee(**overrides):
    data = {
        "doc_id": "E100",
        "full_name": "Beto Ruiz",
        "position": "Profesor",
        "is_active": True,
        "has_lunch": True,
        "lunch_type": "Normal",
    }
    data.update(overrides)

    db = SessionLocal()
    try:
        employee = models.Employee(**data)
        db.add(employee)
        db.commit()
        db.refresh(employee)
        return employee
    finally:
        db.close()


def get_door_id() -> int:
    db = SessionLocal()
    try:
        return db.query(models.Door).first().id
    finally:
        db.close()
