import io
import zipfile

from openpyxl import Workbook
from PIL import Image

from app import models
from app.database import SessionLocal
from app.utils.media import UploadError
from tests.conftest import ADMIN_PASSWORD
from tests.helpers import create_student, csrf_headers, login


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(output, format="PNG")
    return output.getvalue()


PNG = _png_bytes()


def _xlsx(rows: list[list]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _post(client, path, data=None, files=None):
    return client.post(
        path,
        data=data or {},
        files=files,
        headers=csrf_headers(client),
        follow_redirects=False,
    )


def _upload_xlsx(client, path, rows):
    return _post(
        client,
        path,
        files={
            "file": (
                "datos.xlsx",
                _xlsx(rows),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


def _student(student_id: str) -> models.Student | None:
    db = SessionLocal()
    try:
        return db.query(models.Student).filter_by(student_id=student_id).first()
    finally:
        db.close()


def _audit_rows(action: str) -> list[models.AuditLog]:
    db = SessionLocal()
    try:
        return db.query(models.AuditLog).filter_by(action=action).all()
    finally:
        db.close()


def test_list_students_supports_search_and_pagination(client):
    login(client, "admin", ADMIN_PASSWORD)
    for index in range(11):
        create_student(student_id=f"S{700 + index}", full_name=f"Alumno Numero {index}")

    page_two = client.get("/students/?page=2")
    assert page_two.status_code == 200

    by_name = client.get("/students/?q=Alumno Numero 10")
    assert by_name.status_code == 200
    assert "Alumno Numero 10" in by_name.text
    assert "Alumno Numero 9" not in by_name.text

    by_id = client.get("/students/?q=S709")
    assert by_id.status_code == 200
    assert "S709" in by_id.text


def test_list_students_rejects_invalid_page(client):
    login(client, "admin", ADMIN_PASSWORD)

    assert client.get("/students/?page=0").status_code == 422


def test_create_student_rejects_invalid_and_duplicate_ids(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_student(student_id="S100")

    invalid = _post(
        client,
        "/students/create",
        {"student_id": "12.34", "full_name": "Sin ID", "course": "10A"},
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]

    duplicate = _post(
        client,
        "/students/create",
        {"student_id": "S100", "full_name": "Duplicado", "course": "10A"},
    )
    assert duplicate.status_code == 303
    assert "error=" in duplicate.headers["location"]


def test_create_student_handles_photo_storage_failure(client, monkeypatch):
    login(client, "admin", ADMIN_PASSWORD)

    def fail_store(*args, **kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr("app.routers.students.store_photo", fail_store)

    response = _post(
        client,
        "/students/create",
        {"student_id": "S410", "full_name": "Ana Perez", "course": "10A"},
        files={"photo": ("foto.png", PNG, "image/png")},
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert _student("S410") is None


def test_create_student_is_audited(client):
    login(client, "admin", ADMIN_PASSWORD)

    response = _post(
        client,
        "/students/create",
        {
            "student_id": "S411",
            "full_name": "Carla Rojas",
            "course": "11B",
            "is_authorized": "on",
        },
    )

    assert response.status_code == 303
    assert "error=" not in response.headers["location"]
    student = _student("S411")
    assert student is not None
    assert student.is_authorized is True
    audits = _audit_rows("student.created")
    assert len(audits) == 1
    assert audits[0].details["student_id"] == "S411"


def test_toggle_authorization_is_audited_and_missing_student_is_ignored(client):
    login(client, "admin", ADMIN_PASSWORD)
    student = create_student(student_id="S412", is_authorized=True)

    response = _post(client, f"/students/toggle_auth/{student.id}")
    assert response.status_code == 303

    db = SessionLocal()
    try:
        assert db.query(models.Student).filter_by(id=student.id).one().is_authorized is False
    finally:
        db.close()

    audits = _audit_rows("student.authorization_changed")
    assert len(audits) == 1
    assert audits[0].details == {"student_id": "S412", "previous": True, "new": False}

    missing = _post(client, "/students/toggle_auth/999999")
    assert missing.status_code == 303
    assert len(_audit_rows("student.authorization_changed")) == 1


def test_import_students_creates_updates_and_skips(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_student(student_id="S100", full_name="Nombre Antiguo", course="9A")

    response = _upload_xlsx(
        client,
        "/students/import",
        [
            ["ID", "Nombre Completo", "Curso", "Autorizado (SI/NO)"],
            ["S500", "Nuevo Alumno", "10A", "SI"],
            ["S100", "Nombre Actualizado", "11B", "NO"],
            ["", "Sin ID", "9A", "SI"],
        ],
    )

    assert response.status_code == 303
    assert "error=" not in response.headers["location"]
    assert _student("S500").is_authorized is True
    updated = _student("S100")
    assert updated.full_name == "Nombre Actualizado"
    assert updated.course == "11B"
    assert updated.is_authorized is False

    audits = _audit_rows("students.imported")
    assert len(audits) == 1
    assert audits[0].details["processed"] == 2
    assert audits[0].details["skipped"] == 1


def test_import_students_rejects_invalid_extension_and_empty_file(client):
    login(client, "admin", ADMIN_PASSWORD)

    invalid = _post(
        client,
        "/students/import",
        files={"file": ("datos.txt", b"contenido", "text/plain")},
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]

    empty = _post(
        client,
        "/students/import",
        files={"file": ("datos.xlsx", b"", "application/vnd.ms-excel")},
    )
    assert empty.status_code == 303
    assert "error=" in empty.headers["location"]


def test_import_students_handles_parse_errors(client, monkeypatch):
    login(client, "admin", ADMIN_PASSWORD)

    def broken_read(data):
        raise RuntimeError("excel roto")

    monkeypatch.setattr("app.routers.students.read_excel", broken_read)

    response = _upload_xlsx(client, "/students/import", [["S501", "Nombre", "10A", "SI"]])

    assert response.status_code == 303
    assert "error=" in response.headers["location"]


def test_import_photos_updates_known_students_and_counts_skips(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_student(student_id="S201")

    response = _post(
        client,
        "/students/import-photos",
        files={
            "file": (
                "fotos.zip",
                _zip_bytes(
                    {
                        "bad.id.png": PNG,
                        "S999.png": PNG,
                        "S201.png": PNG,
                    }
                ),
                "application/zip",
            )
        },
    )

    assert response.status_code == 303
    assert "error=" not in response.headers["location"]
    assert _student("S201").photo_path == "S201.png"

    audits = _audit_rows("students.photos_imported")
    assert len(audits) == 1
    assert audits[0].details["processed"] == 1
    assert audits[0].details["skipped"] == 2


def test_import_photos_handles_upload_errors(client, monkeypatch):
    login(client, "admin", ADMIN_PASSWORD)

    invalid = _post(
        client,
        "/students/import-photos",
        files={"file": ("fotos.txt", b"no es zip", "text/plain")},
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]

    def invalid_zip(upload):
        raise UploadError("ZIP inválido")

    monkeypatch.setattr("app.routers.students.zip_photo_entries", invalid_zip)
    broken = _post(
        client,
        "/students/import-photos",
        files={"file": ("fotos.zip", b"cualquier cosa", "application/zip")},
    )
    assert broken.status_code == 303
    assert "error=" in broken.headers["location"]

    def unreadable_zip(upload):
        raise ValueError("zip corrupto")

    monkeypatch.setattr("app.routers.students.zip_photo_entries", unreadable_zip)
    unreadable = _post(
        client,
        "/students/import-photos",
        files={"file": ("fotos.zip", b"cualquier cosa", "application/zip")},
    )
    assert unreadable.status_code == 303
    assert "error=" in unreadable.headers["location"]


def test_import_photos_skips_storage_failures(client, monkeypatch):
    login(client, "admin", ADMIN_PASSWORD)
    student = create_student(student_id="S202")

    def fail_store(*args, **kwargs):
        raise OSError("sin espacio")

    monkeypatch.setattr("app.routers.students.store_photo", fail_store)

    response = _post(
        client,
        "/students/import-photos",
        files={"file": ("fotos.zip", _zip_bytes({"S202.png": PNG}), "application/zip")},
    )

    assert response.status_code == 303
    assert "error=" not in response.headers["location"]
    fresh = _student("S202")
    assert fresh.id == student.id
    assert fresh.photo_path is None

    audits = _audit_rows("students.photos_imported")
    assert audits[0].details["processed"] == 0
    assert audits[0].details["skipped"] == 1


def test_update_lunch_groups_assigns_types(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_student(student_id="S201", has_lunch=True, lunch_type="Normal")
    create_student(student_id="S202", has_lunch=False, lunch_type="Ninguno")
    create_student(student_id="S203", has_lunch=True, lunch_type="Normal")

    response = _upload_xlsx(
        client,
        "/students/update-lunch-groups",
        [
            ["ID", "Grupos"],
            ["S201", "Grupo ALMUERZO ESPECIAL"],
            ["S202", "Grupo ALMUERZO NORMAL"],
            ["S203", "Grupo sin beneficio"],
            ["", "ALMUERZO NORMAL"],
            ["S999", "ALMUERZO NORMAL"],
        ],
    )

    assert response.status_code == 303
    assert "error=" not in response.headers["location"]

    especial = _student("S201")
    assert especial.has_lunch is True
    assert especial.lunch_type == models.LunchType.ESPECIAL.value
    normal = _student("S202")
    assert normal.has_lunch is True
    assert normal.lunch_type == models.LunchType.NORMAL.value
    none = _student("S203")
    assert none.has_lunch is False
    assert none.lunch_type == models.LunchType.NONE.value

    audits = _audit_rows("students.lunch_groups_imported")
    assert audits[0].details["updated"] == 3
    assert audits[0].details["skipped"] == 1


def test_update_lunch_groups_handles_invalid_files(client, monkeypatch):
    login(client, "admin", ADMIN_PASSWORD)

    invalid = _post(
        client,
        "/students/update-lunch-groups",
        files={"file": ("grupos.txt", b"datos", "text/plain")},
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]

    def broken_read(data):
        raise RuntimeError("excel roto")

    monkeypatch.setattr("app.routers.students.read_excel", broken_read)
    broken = _upload_xlsx(client, "/students/update-lunch-groups", [["S201", "ALMUERZO NORMAL"]])
    assert broken.status_code == 303
    assert "error=" in broken.headers["location"]


def test_update_rfid_assigns_and_skips_duplicates(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_student(student_id="S201")
    create_student(student_id="S202")
    create_student(student_id="S203", rfid_code="RF2")

    response = _upload_xlsx(
        client,
        "/students/update-rfid",
        [
            ["ID", "RFID"],
            ["S201", "RF1"],
            ["S202", "RF1"],
            ["S201", "RF2"],
            ["S999", "RF3"],
            ["", "RF4"],
            ["S202", None],
        ],
    )

    assert response.status_code == 303
    assert "error=" not in response.headers["location"]
    assert _student("S201").rfid_code == "RF1"
    assert _student("S202").rfid_code is None
    assert _student("S203").rfid_code == "RF2"

    audits = _audit_rows("students.rfid_imported")
    assert audits[0].details["updated"] == 1
    assert audits[0].details["skipped"] == 5


def test_update_rfid_handles_invalid_files(client, monkeypatch):
    login(client, "admin", ADMIN_PASSWORD)

    invalid = _post(
        client,
        "/students/update-rfid",
        files={"file": ("rfid.txt", b"datos", "text/plain")},
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]

    def broken_read(data):
        raise RuntimeError("excel roto")

    monkeypatch.setattr("app.routers.students.read_excel", broken_read)
    broken = _upload_xlsx(client, "/students/update-rfid", [["S201", "RF1"]])
    assert broken.status_code == 303
    assert "error=" in broken.headers["location"]
