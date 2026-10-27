import io
from datetime import date, datetime, timezone

from openpyxl import Workbook
from PIL import Image

from app import models
from app.database import SessionLocal
from tests.conftest import ADMIN_PASSWORD
from tests.helpers import create_employee, csrf_headers, login


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(output, format="PNG")
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


def _employee(doc_id: str) -> models.Employee | None:
    db = SessionLocal()
    try:
        return db.query(models.Employee).filter_by(doc_id=doc_id).first()
    finally:
        db.close()


def _audit_rows(action: str) -> list[models.AuditLog]:
    db = SessionLocal()
    try:
        return db.query(models.AuditLog).filter_by(action=action).all()
    finally:
        db.close()


def _admin_id() -> int:
    db = SessionLocal()
    try:
        return db.query(models.User).filter_by(username="admin").one().id
    finally:
        db.close()


def test_list_employees_supports_search_and_page_clamping(client):
    login(client, "admin", ADMIN_PASSWORD)
    for index in range(22):
        create_employee(doc_id=f"E{800 + index}", full_name=f"Empleado Numero {index:02d}")
    create_employee(doc_id="E900", full_name="Zoe Unica")

    assert client.get("/employees/").status_code == 200
    assert client.get("/employees/?page=2").status_code == 200
    assert client.get("/employees/?page=0").status_code == 200
    assert client.get("/employees/?page=99").status_code == 200

    by_name = client.get("/employees/?search=Zoe Unica")
    assert by_name.status_code == 200
    assert "Zoe Unica" in by_name.text
    assert "Empleado Numero 00" not in by_name.text

    by_doc = client.get("/employees/?search=E900")
    assert by_doc.status_code == 200
    assert "Zoe Unica" in by_doc.text


def test_create_employee_rejects_invalid_and_duplicate_documents(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_employee(doc_id="E100")

    invalid = _post(
        client,
        "/employees/create",
        {"doc_id": "12.34", "full_name": "Sin ID", "position": "Monitor"},
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]

    duplicate = _post(
        client,
        "/employees/create",
        {"doc_id": "E100", "full_name": "Duplicado", "position": "Monitor"},
    )
    assert duplicate.status_code == 303
    assert "error=" in duplicate.headers["location"]


def test_create_employee_handles_invalid_photo_and_lunch_type(client):
    login(client, "admin", ADMIN_PASSWORD)

    bad_photo = _post(
        client,
        "/employees/create",
        {"doc_id": "E510", "full_name": "Foto Mala", "position": "Monitor"},
        files={"photo": ("foto.png", b"no soy imagen", "image/png")},
    )
    assert bad_photo.status_code == 303
    assert "error=" in bad_photo.headers["location"]
    assert _employee("E510") is None

    odd_lunch = _post(
        client,
        "/employees/create",
        {
            "doc_id": "E511",
            "full_name": "Almuerzo Raro",
            "position": "Monitor",
            "has_lunch": "on",
            "lunch_type": "Invalido",
        },
    )
    assert odd_lunch.status_code == 303
    assert "error=" not in odd_lunch.headers["location"]
    employee = _employee("E511")
    assert employee.lunch_type == models.LunchType.NONE.value


def test_create_employee_handles_photo_storage_failure(client, monkeypatch):
    login(client, "admin", ADMIN_PASSWORD)

    def fail_store(*args, **kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr("app.routers.employees.store_photo", fail_store)

    response = _post(
        client,
        "/employees/create",
        {"doc_id": "E512", "full_name": "Beto Ruiz", "position": "Profesor"},
        files={"photo": ("foto.png", PNG, "image/png")},
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert _employee("E512") is None


def test_create_employee_is_audited(client):
    login(client, "admin", ADMIN_PASSWORD)

    response = _post(
        client,
        "/employees/create",
        {
            "doc_id": "E513",
            "full_name": "Carla Docente",
            "position": "Profesora",
            "has_lunch": "on",
            "lunch_type": "Normal",
        },
    )

    assert response.status_code == 303
    assert "error=" not in response.headers["location"]
    employee = _employee("E513")
    assert employee.has_lunch is True
    audits = _audit_rows("employee.created")
    assert len(audits) == 1
    assert audits[0].details["doc_id"] == "E513"


def test_delete_employee_without_history_removes_record(client):
    login(client, "admin", ADMIN_PASSWORD)
    employee = create_employee(doc_id="E600")

    response = _post(client, f"/employees/delete/{employee.id}")

    assert response.status_code == 303
    assert "error=" not in response.headers["location"]
    assert _employee("E600") is None
    audits = _audit_rows("employee.deleted")
    assert len(audits) == 1
    assert audits[0].details["doc_id"] == "E600"


def test_delete_employee_with_history_deactivates_record(client):
    login(client, "admin", ADMIN_PASSWORD)
    with_lunch = create_employee(doc_id="E601")
    with_scan = create_employee(doc_id="E602")

    db = SessionLocal()
    try:
        db.add(
            models.LunchLog(
                service_date=date.today(),
                employee_id=with_lunch.id,
                operator_id=_admin_id(),
                timestamp=datetime.now(timezone.utc),
                delivered_type="Normal",
            )
        )
        db.add(
            models.ScanAttempt(
                module="lunch",
                method="qr",
                result="ok",
                employee_id=with_scan.id,
            )
        )
        db.commit()
    finally:
        db.close()

    lunch_response = _post(client, f"/employees/delete/{with_lunch.id}")
    scan_response = _post(client, f"/employees/delete/{with_scan.id}")

    assert lunch_response.status_code == 303
    assert scan_response.status_code == 303
    assert _employee("E601").is_active is False
    assert _employee("E602").is_active is False
    audits = _audit_rows("employee.deactivated")
    assert len(audits) == 2
    assert {audit.details["doc_id"] for audit in audits} == {"E601", "E602"}


def test_delete_missing_employee_returns_error(client):
    login(client, "admin", ADMIN_PASSWORD)

    response = _post(client, "/employees/delete/999999")

    assert response.status_code == 303
    assert "error=" in response.headers["location"]


def test_import_basic_creates_and_skips_employees(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_employee(doc_id="E100", full_name="Existente")

    response = _upload_xlsx(
        client,
        "/employees/import-basic",
        [
            ["ID", "Nombre", "Cargo"],
            ["E1", "Nuevo Empleado", "Profesor"],
            ["", "Sin ID", "Monitor"],
            ["E100", "Existente", "Coordinador"],
            ["E2", "Otro Empleado", "Monitor"],
        ],
    )

    assert response.status_code == 303
    assert "error=" not in response.headers["location"]
    assert _employee("E1").full_name == "Nuevo Empleado"
    assert _employee("E2").position == "Monitor"
    assert _employee("E100").position == "Profesor"

    audits = _audit_rows("employees.imported")
    assert len(audits) == 1
    assert audits[0].details["processed"] == 2
    assert audits[0].details["skipped"] == 2


def test_import_basic_handles_invalid_files(client, monkeypatch):
    login(client, "admin", ADMIN_PASSWORD)

    invalid = _post(
        client,
        "/employees/import-basic",
        files={"file": ("datos.txt", b"datos", "text/plain")},
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]

    empty = _post(
        client,
        "/employees/import-basic",
        files={"file": ("datos.xlsx", b"", "application/vnd.ms-excel")},
    )
    assert empty.status_code == 303
    assert "error=" in empty.headers["location"]

    def broken_read(data):
        raise RuntimeError("excel roto")

    monkeypatch.setattr("app.routers.employees.read_excel", broken_read)
    broken = _upload_xlsx(client, "/employees/import-basic", [["E3", "Nombre", "Cargo"]])
    assert broken.status_code == 303
    assert "error=" in broken.headers["location"]


def test_update_lunch_groups_assigns_types(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_employee(doc_id="E201", has_lunch=True, lunch_type="Normal")
    create_employee(doc_id="E202", has_lunch=False, lunch_type="Ninguno")
    create_employee(doc_id="E203", has_lunch=True, lunch_type="Normal")

    response = _upload_xlsx(
        client,
        "/employees/update-lunch-groups",
        [
            ["ID", "Grupos"],
            ["E201", "Grupo ALMUERZO ESPECIAL"],
            ["E202", "Grupo ALMUERZO NORMAL"],
            ["E203", "Grupo sin beneficio"],
            ["", "ALMUERZO NORMAL"],
            ["E999", "ALMUERZO NORMAL"],
        ],
    )

    assert response.status_code == 303
    assert "error=" not in response.headers["location"]

    especial = _employee("E201")
    assert especial.has_lunch is True
    assert especial.lunch_type == models.LunchType.ESPECIAL.value
    normal = _employee("E202")
    assert normal.has_lunch is True
    assert normal.lunch_type == models.LunchType.NORMAL.value
    none = _employee("E203")
    assert none.has_lunch is False
    assert none.lunch_type == models.LunchType.NONE.value

    audits = _audit_rows("employees.lunch_groups_imported")
    assert audits[0].details["updated"] == 3
    assert audits[0].details["skipped"] == 1


def test_update_lunch_groups_handles_invalid_files(client, monkeypatch):
    login(client, "admin", ADMIN_PASSWORD)

    invalid = _post(
        client,
        "/employees/update-lunch-groups",
        files={"file": ("grupos.txt", b"datos", "text/plain")},
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]

    def broken_read(data):
        raise RuntimeError("excel roto")

    monkeypatch.setattr("app.routers.employees.read_excel", broken_read)
    broken = _upload_xlsx(client, "/employees/update-lunch-groups", [["E201", "ALMUERZO NORMAL"]])
    assert broken.status_code == 303
    assert "error=" in broken.headers["location"]


def test_update_rfid_assigns_and_skips_duplicates(client):
    login(client, "admin", ADMIN_PASSWORD)
    create_employee(doc_id="E201")
    create_employee(doc_id="E202")
    create_employee(doc_id="E203", rfid_code="RF2")

    response = _upload_xlsx(
        client,
        "/employees/update-rfid",
        [
            ["ID", "RFID"],
            ["E201", "RF1"],
            ["E202", "RF1"],
            ["E201", "RF2"],
            ["E999", "RF3"],
            ["", "RF4"],
            ["E202", None],
        ],
    )

    assert response.status_code == 303
    assert "error=" not in response.headers["location"]
    assert _employee("E201").rfid_code == "RF1"
    assert _employee("E202").rfid_code is None
    assert _employee("E203").rfid_code == "RF2"

    audits = _audit_rows("employees.rfid_imported")
    assert audits[0].details["updated"] == 1
    assert audits[0].details["skipped"] == 5


def test_update_rfid_handles_invalid_files(client, monkeypatch):
    login(client, "admin", ADMIN_PASSWORD)

    invalid = _post(
        client,
        "/employees/update-rfid",
        files={"file": ("rfid.txt", b"datos", "text/plain")},
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]

    def broken_read(data):
        raise RuntimeError("excel roto")

    monkeypatch.setattr("app.routers.employees.read_excel", broken_read)
    broken = _upload_xlsx(client, "/employees/update-rfid", [["E201", "RF1"]])
    assert broken.status_code == 303
    assert "error=" in broken.headers["location"]


def test_update_employee_validates_input_and_persists_changes(client):
    login(client, "admin", ADMIN_PASSWORD)
    employee = create_employee(doc_id="E100")
    create_employee(doc_id="E101")
    other = _employee("E101")

    missing = _post(
        client,
        "/employees/update",
        {"id": 999999, "doc_id": "E998", "full_name": "Nadie", "position": "Monitor"},
    )
    assert missing.status_code == 303
    assert "error=" in missing.headers["location"]

    invalid = _post(
        client,
        "/employees/update",
        {"id": employee.id, "doc_id": "1.2", "full_name": "Nombre", "position": "Monitor"},
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]

    duplicate = _post(
        client,
        "/employees/update",
        {"id": employee.id, "doc_id": "E101", "full_name": "Nombre", "position": "Monitor"},
    )
    assert duplicate.status_code == 303
    assert "error=" in duplicate.headers["location"]
    assert _employee("E101").id == other.id

    invalid_lunch = _post(
        client,
        "/employees/update",
        {
            "id": employee.id,
            "doc_id": "E200",
            "full_name": "Beto Actualizado",
            "position": "Coordinador",
            "lunch_type": "Invalido",
        },
    )
    assert invalid_lunch.status_code == 303
    assert "error=" not in invalid_lunch.headers["location"]
    updated = _employee("E200")
    assert updated.full_name == "Beto Actualizado"
    assert updated.position == "Coordinador"
    assert updated.has_lunch is False
    assert updated.lunch_type == models.LunchType.NONE.value

    audits = _audit_rows("employee.updated")
    assert len(audits) == 1
    assert audits[0].details["photo_updated"] is False


def test_update_employee_handles_photo_errors(client, monkeypatch):
    login(client, "admin", ADMIN_PASSWORD)
    employee = create_employee(doc_id="E300")

    bad_photo = _post(
        client,
        "/employees/update",
        {"id": employee.id, "doc_id": "E300", "full_name": "Beto Ruiz", "position": "Profesor"},
        files={"photo": ("foto.png", b"no soy imagen", "image/png")},
    )
    assert bad_photo.status_code == 303
    assert "error=" in bad_photo.headers["location"]

    def fail_store(*args, **kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr("app.routers.employees.store_photo", fail_store)
    storage_error = _post(
        client,
        "/employees/update",
        {"id": employee.id, "doc_id": "E300", "full_name": "Beto Ruiz", "position": "Profesor"},
        files={"photo": ("foto.png", PNG, "image/png")},
    )
    assert storage_error.status_code == 303
    assert "error=" in storage_error.headers["location"]
    assert _employee("E300").photo_path is None
