import base64

from app import models
from app.config import settings
from app.database import SessionLocal
from tests.conftest import USER_PASSWORD
from tests.helpers import create_student, login

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


def _student_with_photo():
    student = create_student(student_id="S400")
    directory = settings.media_photos_dir / "students"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "S400.png").write_bytes(PNG)

    db = SessionLocal()
    try:
        row = db.query(models.Student).filter_by(id=student.id).one()
        row.photo_path = "S400.png"
        db.commit()
    finally:
        db.close()
    return student


def test_photos_require_authentication(client):
    student = _student_with_photo()

    assert client.get(f"/media/photos/students/{student.student_id}.png").status_code == 401
    assert client.get("/static/photos/S400.png").status_code == 404


def test_authenticated_photo_is_private_and_scoped(client):
    _student_with_photo()
    login(client, "operator", USER_PASSWORD)

    response = client.get("/media/photos/students/S400.png")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-type"].startswith("image/png")

    assert client.get("/media/photos/employees/S400.png").status_code == 404
    assert client.get("/media/photos/students/other.png").status_code == 404
    assert client.get("/media/photos/students/S400.txt").status_code == 404
    assert client.get("/media/photos/students/..%2fS400.png").status_code == 404
