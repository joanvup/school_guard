from fastapi import APIRouter, Depends, Form, UploadFile, File, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from urllib.parse import quote_plus
import math
from typing import Optional
from .. import database, models, deps
from ..services.audit import add_audit
from ..utils.data import clean_text, normalize_excel_id, normalize_rfid, read_excel
from ..utils.media import UploadError, normalize_photo, read_upload, store_photo

router = APIRouter(
    prefix="/employees", tags=["Employees"], dependencies=[Depends(deps.require_admin)]
)

templates = Jinja2Templates(directory="app/templates")


def _error(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/employees?error={quote_plus(message)}", status_code=303)


# --- VISTA LISTADO ---
@router.get("/")
def list_employees(
    request: Request, page: int = 1, search: str = "", db: Session = Depends(database.get_db)
):
    limit = 20
    query = db.query(models.Employee)

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                models.Employee.full_name.like(search_pattern),
                models.Employee.doc_id.like(search_pattern),
            )
        )

    total_records = query.count()
    total_pages = math.ceil(total_records / limit)

    if page < 1:
        page = 1
    if page > total_pages and total_pages > 0:
        page = total_pages
    offset = (page - 1) * limit

    employees = query.order_by(models.Employee.full_name.asc()).offset(offset).limit(limit).all()

    return templates.TemplateResponse(
        "employees.html",
        {
            "request": request,
            "employees": employees,
            "page": page,
            "total_pages": total_pages,
            "search": search,
            "user": request.state.user,
        },
    )


# --- ACCIONES CRUD ---


@router.post("/create")
def create_employee(
    request: Request,
    doc_id: str = Form(...),
    full_name: str = Form(...),
    position: str = Form(None),
    has_lunch: bool = Form(False),
    lunch_type: str = Form("Normal"),  # Viene como texto: "Normal" o "Especial"
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(database.get_db),
):
    doc_id = normalize_excel_id(doc_id)
    if not doc_id:
        return _error("Cédula inválida")
    if db.query(models.Employee).filter(models.Employee.doc_id == doc_id).first():
        return _error("Cédula ya existe")

    photo_data = None
    if photo and photo.filename:
        try:
            photo_data = normalize_photo(photo)
        except UploadError as exc:
            return _error(str(exc))

    try:
        enum_obj = models.LunchType(lunch_type)
        lunch_value = enum_obj.value
    except ValueError:
        lunch_value = "Ninguno"

    new_emp = models.Employee(
        doc_id=doc_id,
        full_name=full_name,
        position=position,
        has_lunch=has_lunch,
        lunch_type=lunch_value,
    )
    if photo_data is not None:
        try:
            new_emp.photo_path = store_photo("employees", f"EMP_{doc_id}", *photo_data)
        except (UploadError, OSError):
            return _error("No se pudo guardar la foto")

    db.add(new_emp)
    db.flush()
    add_audit(
        db,
        action="employee.created",
        actor_id=request.state.user.id,
        entity_type="employee",
        entity_id=new_emp.id,
        details={
            "doc_id": new_emp.doc_id,
            "has_lunch": bool(new_emp.has_lunch),
            "lunch_type": new_emp.lunch_type,
        },
        request=request,
    )
    db.commit()
    return RedirectResponse(url="/employees?msg=Empleado+creado", status_code=303)


@router.post("/delete/{id}")
def delete_employee(id: int, request: Request, db: Session = Depends(database.get_db)):
    emp = db.query(models.Employee).filter(models.Employee.id == id).first()
    if not emp:
        return _error("Empleado no encontrado")

    lunch_records = db.query(models.LunchLog).filter(models.LunchLog.employee_id == id).count()
    scan_records = db.query(models.ScanAttempt).filter(models.ScanAttempt.employee_id == id).count()
    has_history = lunch_records > 0 or scan_records > 0

    doc_id = emp.doc_id
    if has_history:
        emp.is_active = False
        action = "employee.deactivated"
        message = "Empleado desactivado para conservar el historial"
    else:
        db.delete(emp)
        action = "employee.deleted"
        message = "Empleado eliminado"

    add_audit(
        db,
        action=action,
        actor_id=request.state.user.id,
        entity_type="employee",
        entity_id=id,
        details={
            "doc_id": doc_id,
            "lunch_records": lunch_records,
            "scan_records": scan_records,
        },
        request=request,
    )
    db.commit()
    return RedirectResponse(url=f"/employees?msg={quote_plus(message)}", status_code=303)


# --- IMPORTACIONES ---


@router.post("/import-basic")
def import_basic(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
):
    """Carga inicial de empleados (ID, Nombre, Cargo)"""
    if not (file.filename or "").lower().endswith((".xls", ".xlsx")):
        return _error("Formato inválido")
    try:
        df = read_excel(read_upload(file))
        count = 0
        skipped = 0
        for _, row in df.iterrows():
            did = normalize_excel_id(row.iloc[0])
            name = clean_text(row.iloc[1])
            pos = clean_text(row.iloc[2]) if len(row) > 2 else ""
            if not did or not name:
                skipped += 1
                continue

            existing = db.query(models.Employee).filter(models.Employee.doc_id == did).first()
            if not existing:
                db.add(models.Employee(doc_id=did, full_name=name, position=pos))
                count += 1
            else:
                skipped += 1
        add_audit(
            db,
            action="employees.imported",
            actor_id=request.state.user.id,
            entity_type="employee",
            details={"processed": count, "skipped": skipped, "filename": file.filename},
            request=request,
        )
        db.commit()
        message = f"Creados+{count}+empleados"
        if skipped:
            message += f"+({skipped}+omitidos)"
        return RedirectResponse(f"/employees?msg={message}", 303)
    except Exception:
        return RedirectResponse("/employees?error=Error+archivo", 303)


@router.post("/update-lunch-groups")
def update_lunch_groups(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
):
    """
    Actualiza permisos de almuerzo basado en columna 'grupos'.
    Logica: Busca 'ALMUERZO NORMAL' o 'ALMUERZO ESPECIAL'.
    """
    if not (file.filename or "").lower().endswith((".xls", ".xlsx")):
        return _error("Formato inválido")
    try:
        df = read_excel(read_upload(file))
        updated = 0
        skipped = 0

        # Asumimos Col 0: ID, Col 1: Grupos (Texto largo)
        for _, row in df.iterrows():
            did = normalize_excel_id(row.iloc[0])
            if not did:
                skipped += 1
                continue
            raw_groups = clean_text(row.iloc[1]).upper()

            emp = db.query(models.Employee).filter(models.Employee.doc_id == did).first()
            if emp:
                if "ALMUERZO NORMAL" in raw_groups:
                    emp.has_lunch = True
                    emp.lunch_type = models.LunchType.NORMAL.value
                elif "ALMUERZO ESPECIAL" in raw_groups:
                    emp.has_lunch = True
                    emp.lunch_type = models.LunchType.ESPECIAL.value
                else:
                    # Si no aparece ninguno, quitamos el almuerzo
                    emp.has_lunch = False
                    emp.lunch_type = models.LunchType.NONE.value
                updated += 1

        add_audit(
            db,
            action="employees.lunch_groups_imported",
            actor_id=request.state.user.id,
            entity_type="employee",
            details={"updated": updated, "skipped": skipped, "filename": file.filename},
            request=request,
        )
        db.commit()
        return RedirectResponse(f"/employees?msg=Almuerzos+actualizados:+{updated}", 303)
    except Exception:
        return _error("Error procesando grupos")


@router.post("/update-rfid")
def update_rfid(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
):
    """Actualiza solo el código RFID. Col 0: ID, Col 1: RFID"""
    if not (file.filename or "").lower().endswith((".xls", ".xlsx")):
        return _error("Formato inválido")
    try:
        df = read_excel(read_upload(file))
        updated = 0
        skipped = 0
        seen_rfid: set[str] = set()
        for _, row in df.iterrows():
            did = normalize_excel_id(row.iloc[0])
            rfid = normalize_rfid(row.iloc[1])
            if not did or not rfid:
                skipped += 1
                continue

            emp = db.query(models.Employee).filter(models.Employee.doc_id == did).first()
            if not emp or rfid in seen_rfid:
                skipped += 1
                continue
            duplicate = (
                db.query(models.Employee)
                .filter(
                    models.Employee.rfid_code == rfid,
                    models.Employee.id != emp.id,
                )
                .first()
            )
            if duplicate:
                skipped += 1
                continue

            seen_rfid.add(rfid)
            emp.rfid_code = rfid
            updated += 1
        add_audit(
            db,
            action="employees.rfid_imported",
            actor_id=request.state.user.id,
            entity_type="employee",
            details={"updated": updated, "skipped": skipped, "filename": file.filename},
            request=request,
        )
        db.commit()
        message = f"RFIDs actualizados: {updated}"
        if skipped:
            message += f" ({skipped} omitidos)"
        return RedirectResponse(f"/employees?msg={quote_plus(message)}", 303)
    except Exception:
        return _error("Error al procesar el archivo")


@router.post("/update")
def update_employee(
    request: Request,
    id: int = Form(...),
    doc_id: str = Form(...),
    full_name: str = Form(...),
    position: str = Form(None),
    has_lunch: bool = Form(False),
    lunch_type: str = Form("Normal"),
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(database.get_db),
):
    emp = db.query(models.Employee).filter(models.Employee.id == id).first()
    if not emp:
        return _error("Empleado no encontrado")

    doc_id = normalize_excel_id(doc_id)
    if not doc_id:
        return _error("Cédula inválida")
    duplicate = (
        db.query(models.Employee)
        .filter(
            models.Employee.doc_id == doc_id,
            models.Employee.id != id,
        )
        .first()
    )
    if duplicate:
        return _error("Cédula ya existe")

    photo_data = None
    if photo and photo.filename:
        try:
            photo_data = normalize_photo(photo)
        except UploadError as exc:
            return _error(str(exc))

    # Actualizar datos básicos
    emp.doc_id = doc_id
    emp.full_name = full_name
    emp.position = position
    emp.has_lunch = has_lunch

    # Manejo de Enum/String
    try:
        emp.lunch_type = models.LunchType(lunch_type).value
    except ValueError:
        emp.lunch_type = "Ninguno"

    # Actualizar foto solo si se sube una nueva
    if photo_data is not None:
        try:
            emp.photo_path = store_photo("employees", f"EMP_{doc_id}", *photo_data)
        except (UploadError, OSError):
            return _error("No se pudo guardar la foto")

    add_audit(
        db,
        action="employee.updated",
        actor_id=request.state.user.id,
        entity_type="employee",
        entity_id=emp.id,
        details={
            "doc_id": emp.doc_id,
            "has_lunch": bool(emp.has_lunch),
            "lunch_type": emp.lunch_type,
            "photo_updated": photo_data is not None,
        },
        request=request,
    )
    db.commit()
    return RedirectResponse(url="/employees?msg=Empleado+actualizado", status_code=303)
