from fastapi.testclient import TestClient

from app import database, models
from app.database import SessionLocal
from app.main import app
from tests.conftest import ADMIN_PASSWORD
from tests.helpers import create_student, csrf_headers, login


class BrokenEngine:
    def connect(self):
        raise RuntimeError("database unavailable")


def test_request_id_is_echoed_when_valid(client):
    response = client.get("/healthz", headers={"X-Request-ID": "req-abcdef-1234"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-abcdef-1234"


def test_invalid_request_id_is_replaced(client):
    response = client.get("/healthz", headers={"X-Request-ID": "bad id"})

    assert response.status_code == 200
    request_id = response.headers["X-Request-ID"]
    assert request_id != "bad id"
    assert len(request_id) == 32


def test_healthz_reports_degraded_when_database_is_down(client, monkeypatch):
    monkeypatch.setattr(database, "engine", BrokenEngine())

    response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded"}


def test_audit_records_request_id(client):
    login(client, "admin", ADMIN_PASSWORD)
    student = create_student(student_id="S950")

    response = client.post(
        f"/students/delete/{student.id}",
        headers={**csrf_headers(client), "X-Request-ID": "audit-request-123"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    db = SessionLocal()
    try:
        entry = db.query(models.AuditLog).filter(models.AuditLog.action == "student.deleted").one()
    finally:
        db.close()
    assert entry.request_id == "audit-request-123"


def test_unhandled_exception_is_json_and_keeps_request_id(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.main.deps.get_current_user", boom)

    with TestClient(app, raise_server_exceptions=False) as failing_client:
        response = failing_client.get("/", headers={"X-Request-ID": "error-request-123"})

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Error interno",
        "request_id": "error-request-123",
    }
    assert response.headers["X-Request-ID"] == "error-request-123"
