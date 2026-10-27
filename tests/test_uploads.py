import io
import zipfile

from PIL import Image

from app import models
from app.config import settings
from app.database import SessionLocal
from tests.conftest import ADMIN_PASSWORD
from tests.helpers import create_student, csrf_headers, login


def _image_bytes(image_format: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(output, format=image_format)
    return output.getvalue()


PNG = _image_bytes("PNG")


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


def _upload_photo(client, path, data, content=PNG, filename="foto.png"):
    return client.post(
        path,
        data=data,
        files={"photo": (filename, content, "image/png")},
        headers=csrf_headers(client),
        follow_redirects=False,
    )


def _upload_zip(client, content):
    return client.post(
        "/students/import-photos",
        files={"file": ("fotos.zip", content, "application/zip")},
        headers=csrf_headers(client),
        follow_redirects=False,
    )


def test_valid_png_photo_is_normalized_and_saved(client):
    login(client, "admin", ADMIN_PASSWORD)

    response = _upload_photo(
        client,
        "/students/create",
        {"student_id": "S400", "full_name": "Ana Perez", "course": "10A", "is_authorized": "on"},
    )

    assert response.status_code == 303
    db = SessionLocal()
    try:
        student = db.query(models.Student).filter_by(student_id="S400").one()
        assert student.photo_path == "S400.png"
    finally:
        db.close()

    saved = settings.media_photos_dir / "students" / "S400.png"
    assert saved.is_file()
    with Image.open(saved) as image:
        assert image.format == "PNG"


def test_image_format_is_detected_and_extension_is_canonical(client):
    login(client, "admin", ADMIN_PASSWORD)

    response = _upload_photo(
        client,
        "/students/create",
        {"student_id": "S401", "full_name": "Luis Soto", "course": "11B"},
        content=_image_bytes("JPEG"),
        filename="S401.png",
    )

    assert response.status_code == 303
    db = SessionLocal()
    try:
        student = db.query(models.Student).filter_by(student_id="S401").one()
        assert student.photo_path == "S401.jpg"
    finally:
        db.close()
    assert (settings.media_photos_dir / "students" / "S401.jpg").is_file()


def test_fake_image_is_rejected(client):
    login(client, "admin", ADMIN_PASSWORD)

    response = _upload_photo(
        client,
        "/students/create",
        {"student_id": "S402", "full_name": "Eva Diaz", "course": "9A"},
        content=b"#!/bin/sh\necho no soy una imagen",
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db = SessionLocal()
    try:
        assert db.query(models.Student).filter_by(student_id="S402").first() is None
    finally:
        db.close()


def test_image_with_disallowed_real_format_is_rejected(client):
    login(client, "admin", ADMIN_PASSWORD)

    response = _upload_photo(
        client,
        "/students/create",
        {"student_id": "S403", "full_name": "GIF Falso", "course": "9B"},
        content=_image_bytes("GIF"),
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db = SessionLocal()
    try:
        assert db.query(models.Student).filter_by(student_id="S403").first() is None
    finally:
        db.close()


def test_oversized_photo_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    login(client, "admin", ADMIN_PASSWORD)

    response = _upload_photo(
        client,
        "/students/create",
        {"student_id": "S404", "full_name": "Foto Grande", "course": "8A"},
        content=b"\x89PNG" + b"0" * (1024 * 1024 + 10),
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db = SessionLocal()
    try:
        assert db.query(models.Student).filter_by(student_id="S404").first() is None
    finally:
        db.close()


def test_employee_photo_is_validated(client):
    login(client, "admin", ADMIN_PASSWORD)

    response = _upload_photo(
        client,
        "/employees/create",
        {"doc_id": "E500", "full_name": "Beto Ruiz", "position": "Profesor"},
        filename="cualquiera.png",
    )

    assert response.status_code == 303
    db = SessionLocal()
    try:
        employee = db.query(models.Employee).filter_by(doc_id="E500").one()
        assert employee.photo_path == "EMP_E500.png"
    finally:
        db.close()


def test_valid_zip_updates_student_photo(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_student(student_id="S400")

    response = _upload_zip(client, _zip_bytes({"fotos/S400.png": PNG}))

    assert response.status_code == 303
    db = SessionLocal()
    try:
        student = db.query(models.Student).filter_by(student_id="S400").one()
        assert student.photo_path == "S400.png"
        assert (
            db.query(models.AuditLog)
            .filter(models.AuditLog.action == "students.photos_imported")
            .count()
            == 1
        )
    finally:
        db.close()
    assert (settings.media_photos_dir / "students" / "S400.png").is_file()


def test_zip_with_path_traversal_is_rejected(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_student(student_id="S400")

    response = _upload_zip(client, _zip_bytes({"../evil.png": PNG}))

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db = SessionLocal()
    try:
        student = db.query(models.Student).filter_by(student_id="S400").one()
        assert student.photo_path is None
    finally:
        db.close()
    assert not (settings.media_photos_dir / "evil.png").exists()


def test_zip_with_too_many_entries_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "max_zip_entries", 2)
    login(client, "admin", ADMIN_PASSWORD)

    response = _upload_zip(
        client,
        _zip_bytes({"1.png": PNG, "2.png": PNG, "3.png": PNG}),
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]


def test_zip_bomb_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    login(client, "admin", ADMIN_PASSWORD)
    create_student(student_id="S400")

    bomb = _zip_bytes({"S400.png": b"\0" * (2 * 1024 * 1024)})
    response = _upload_zip(client, bomb)

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db = SessionLocal()
    try:
        student = db.query(models.Student).filter_by(student_id="S400").one()
        assert student.photo_path is None
    finally:
        db.close()
