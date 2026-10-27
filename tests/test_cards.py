import io
import zipfile

from PIL import Image

from app.config import settings
from tests.conftest import ADMIN_PASSWORD
from tests.helpers import create_employee, create_student, login


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PNG")
    return output.getvalue()


def _write_photo(scope: str, filename: str, content: bytes) -> None:
    directory = settings.media_photos_dir / scope
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_bytes(content)


def test_student_card_pdf_is_generated(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_student(student_id="S700", full_name="Ana Perez")

    response = client.get("/cards/pdf/S700")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="carnet_S700.pdf"' in response.headers["Content-Disposition"]
    assert response.content.startswith(b"%PDF")


def test_student_card_pdf_returns_404_when_missing(client):
    login(client, "admin", ADMIN_PASSWORD)

    assert client.get("/cards/pdf/S999").status_code == 404


def test_employee_card_pdf_is_generated(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_employee(doc_id="E700", full_name="Beto Ruiz")

    response = client.get("/cards/employee/pdf/E700")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="carnet_EMP_E700.pdf"' in response.headers["Content-Disposition"]
    assert response.content.startswith(b"%PDF")


def test_employee_card_pdf_returns_404_when_missing(client):
    login(client, "admin", ADMIN_PASSWORD)

    assert client.get("/cards/employee/pdf/E999").status_code == 404


def test_batch_student_cards_cover_long_names_and_photos(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_student(student_id="S700", full_name="Ana Perez")
    create_student(student_id="S701", full_name="Ana Maria Perez Gom")
    create_student(student_id="S702", full_name="Maria Del Carmen Rodriguez Gomez De La Torre")
    create_student(student_id="S703", full_name="Hipermegalargonombreunico")

    create_student(student_id="S704", full_name="Foto Real", photo_path="S704.png")
    _write_photo("students", "S704.png", _png_bytes())

    create_student(student_id="S705", full_name="Foto Rota", photo_path="S705.png")
    _write_photo("students", "S705.png", b"contenido corrupto")

    response = client.get("/cards/batch/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_batch_student_qr_zip_contains_each_student(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_student(student_id="S700")
    create_student(student_id="S701")

    response = client.get("/cards/batch/qr-images")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == ["S700.png", "S701.png"]
        for name in archive.namelist():
            assert archive.read(name).startswith(b"\x89PNG")


def test_employee_batch_pdf_and_qr_zip(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_employee(doc_id="E700", full_name="Beto Ruiz")
    create_employee(doc_id="E701", full_name="Carla Docente")

    pdf = client.get("/cards/employee/batch/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    qrs = client.get("/cards/employee/batch/qr-images")
    assert qrs.status_code == 200
    assert qrs.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(qrs.content)) as archive:
        assert sorted(archive.namelist()) == ["E700.png", "E701.png"]


def test_cards_fall_back_to_placeholder_without_assets(client, monkeypatch):
    login(client, "admin", ADMIN_PASSWORD)
    create_student(student_id="S706", full_name="Sin Recursos")

    monkeypatch.setattr("app.routers.cards.BG_PATH", "ruta/inexistente.png")
    monkeypatch.setattr("app.routers.cards.AVATAR_PATH", "ruta/inexistente.png")

    response = client.get("/cards/pdf/S706")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
