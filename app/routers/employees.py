from fastapi import APIRouter, Depends, Form, UploadFile, File, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
import pandas as pd
import io
import math
import shutil
from typing import Optional
from .. import database, models, deps
from ..config import settings
from ..utils.data import clean_text, normalize_excel_id, normalize_rfid

router = APIRouter(
    prefix="/employees", tags=["Employees"], dependencies=[Depends(deps.require_admin)]
)

templates = Jinja2Templates(directory="app/templates")
PHOTOS_DIR = settings.media_photos_dir / "employees"
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)


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
        return RedirectResponse(url="/employees?error=Cédula+inválida", status_code=303)
    if db.query(models.Employee).filter(models.Employee.doc_id == doc_id).first():
        return RedirectResponse(url="/employees?error=Cédula+ya+existe", status_code=303)

    photo_path = None
    if photo and photo.filename:
        ext = photo.filename.split(".")[-1].lower()
        if ext in ["jpg", "jpeg", "png"]:
            filename = f"EMP_{doc_id}.{ext}"
            file_location = PHOTOS_DIR / filename
            with open(file_location, "wb") as buffer:
                shutil.copyfileobj(photo.file, buffer)
            photo_path = filename

    # --- CORRECCIÓN AQUÍ ---
    # Convertimos el string "Normal" al objeto Enum <LunchType.NORMAL>
    try:
        enum_obj = models.LunchType(lunch_type)
        lunch_value = enum_obj.value  # Extraemos "Normal" o "Especial"
    except ValueError:
        # Si por alguna razón llega un valor raro, asignamos NONE o NORMAL por defecto
        lunch_value = "Ninguno"

    new_emp = models.Employee(
        doc_id=doc_id,
        full_name=full_name,
        position=position,
        has_lunch=has_lunch,
        lunch_type=lunch_value,
        photo_path=photo_path,
    )
    db.add(new_emp)
    db.commit()
    return RedirectResponse(url="/employees?msg=Empleado+creado", status_code=303)


@router.post("/delete/{id}")
def delete_employee(id: int, db: Session = Depends(database.get_db)):
    emp = db.query(models.Employee).filter(models.Employee.id == id).first()
    if not emp:
        return RedirectResponse(url="/employees?error=Empleado+no+encontrado", status_code=303)

    # VERIFICACIÓN DE INTEGRIDAD
    # Contamos si tiene registros de almuerzo asociados
    has_records = db.query(models.LunchLog).filter(models.LunchLog.employee_id == id).count()

    if has_records > 0:
        return RedirectResponse(
            url="/employees?error=No+se+puede+eliminar:+El+empleado+tiene+historial+de+almuerzos.",
            status_code=303,
        )

    # Si no tiene registros, procedemos a borrar
    db.delete(emp)
    db.commit()

    return RedirectResponse(url="/employees?msg=Empleado+eliminado", status_code=303)


# --- IMPORTACIONES ---


@router.post("/import-basic")
def import_basic(file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    """Carga inicial de empleados (ID, Nombre, Cargo)"""
    if not file.filename.endswith((".xls", ".xlsx")):
        return RedirectResponse("/employees?error=Formato+invalido", 303)
    try:
        df = pd.read_excel(io.BytesIO(file.file.read()), dtype=str)
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
        db.commit()
        message = f"Creados+{count}+empleados"
        if skipped:
            message += f"+({skipped}+omitidos)"
        return RedirectResponse(f"/employees?msg={message}", 303)
    except Exception:
        return RedirectResponse("/employees?error=Error+archivo", 303)


@router.post("/update-lunch-groups")
def update_lunch_groups(file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    """
    Actualiza permisos de almuerzo basado en columna 'grupos'.
    Logica: Busca 'ALMUERZO NORMAL' o 'ALMUERZO ESPECIAL'.
    """
    if not file.filename.endswith((".xls", ".xlsx")):
        return RedirectResponse("/employees?error=Formato+invalido", 303)
    try:
        df = pd.read_excel(io.BytesIO(file.file.read()), dtype=str)
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

        db.commit()
        return RedirectResponse(f"/employees?msg=Almuerzos+actualizados:+{updated}", 303)
    except Exception as e:
        print(e)
        return RedirectResponse("/employees?error=Error+procesando+grupos", 303)


@router.post("/update-rfid")
def update_rfid(file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    """Actualiza solo el código RFID. Col 0: ID, Col 1: RFID"""
    if not file.filename.endswith((".xls", ".xlsx")):
        return RedirectResponse("/employees?error=Formato+invalido", 303)
    try:
        df = pd.read_excel(io.BytesIO(file.file.read()), dtype=str)
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
        db.commit()
        message = f"RFIDs+actualizados:+{updated}"
        if skipped:
            message += f"+({skipped}+omitidos)"
        return RedirectResponse(f"/employees?msg={message}", 303)
    except Exception:
        return RedirectResponse("/employees?error=Error+archivo", 303)


@router.post("/update")
def update_employee(
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
        return RedirectResponse(url="/employees?error=Empleado+no+encontrado", status_code=303)

    doc_id = normalize_excel_id(doc_id)
    if not doc_id:
        return RedirectResponse(url="/employees?error=Cédula+inválida", status_code=303)
    duplicate = (
        db.query(models.Employee)
        .filter(
            models.Employee.doc_id == doc_id,
            models.Employee.id != id,
        )
        .first()
    )
    if duplicate:
        return RedirectResponse(url="/employees?error=Cédula+ya+existe", status_code=303)

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
    if photo and photo.filename:
        ext = photo.filename.split(".")[-1].lower()
        if ext in ["jpg", "jpeg", "png"]:
            filename = f"EMP_{doc_id}.{ext}"
            file_location = PHOTOS_DIR / filename
            with open(file_location, "wb") as buffer:
                shutil.copyfileobj(photo.file, buffer)
            emp.photo_path = filename

    db.commit()
    return RedirectResponse(url="/employees?msg=Empleado+actualizado", status_code=303)
