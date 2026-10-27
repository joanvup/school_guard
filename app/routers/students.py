from fastapi import APIRouter, Depends, Form, UploadFile, File, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from urllib.parse import quote_plus
import math
from sqlalchemy import or_
from starlette.requests import Request
from .. import database, models, deps
from ..services.audit import add_audit
from ..utils.data import clean_text, normalize_excel_id, normalize_rfid, read_excel
from ..utils.excel import build_xlsx
from ..utils.media import (
    UploadError,
    normalize_photo,
    read_upload,
    store_photo,
    zip_photo_entries,
)

router = APIRouter(
    prefix="/students", tags=["Students"], dependencies=[Depends(deps.require_admin)]
)

templates = Jinja2Templates(directory="app/templates")


def _error(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/students?error={quote_plus(message)}", status_code=303)


# --- VISTAS ---


@router.get("/")
def list_students(
    request: Request,
    page: int = Query(1, ge=1),  # Página actual, defecto 1
    q: str = Query(None),  # Término de búsqueda
    db: Session = Depends(database.get_db),
):
    LIMIT = 10  # Cantidad de estudiantes por página

    # Consulta base
    query = db.query(models.Student)

    # Aplicar búsqueda si existe
    if q:
        search_fmt = f"%{q}%"
        # Busca por Nombre O por ID
        query = query.filter(
            or_(
                models.Student.full_name.ilike(search_fmt),
                models.Student.student_id.ilike(search_fmt),
            )
        )

    # Contar total de resultados (para saber cuántas páginas hay)
    total_records = query.count()
    total_pages = math.ceil(total_records / LIMIT)

    # Calcular offset
    offset = (page - 1) * LIMIT

    # Obtener registros de la página actual
    # Ordenamos por creación descendente para ver los nuevos, o por nombre si prefieres
    students = query.order_by(models.Student.created_at.desc()).offset(offset).limit(LIMIT).all()

    return templates.TemplateResponse(
        "students.html",
        {
            "request": request,
            "students": students,
            "user": request.state.user,
            # Datos para paginación en el frontend
            "pagination": {
                "page": page,
                "total_pages": total_pages,
                "total_records": total_records,
                "has_next": page < total_pages,
                "has_prev": page > 1,
                "q": q or "",  # Devolver el término de búsqueda para mantenerlo en el input
            },
        },
    )


# --- API / ACCIONES ---


@router.post("/create")
def create_student(
    request: Request,
    student_id: str = Form(...),
    full_name: str = Form(...),
    course: str = Form(...),
    is_authorized: bool = Form(False),
    photo: Optional[UploadFile] = File(None),  # Campo opcional
    db: Session = Depends(database.get_db),
):
    # Verificar duplicados
    student_id = normalize_excel_id(student_id)
    if not student_id:
        return _error("ID inválido")
    if db.query(models.Student).filter(models.Student.student_id == student_id).first():
        return _error("ID duplicado")

    photo_data = None
    if photo and photo.filename:
        try:
            photo_data = normalize_photo(photo)
        except UploadError as exc:
            return _error(str(exc))

    new_student = models.Student(
        student_id=student_id,
        full_name=full_name,
        course=course,
        is_authorized=is_authorized,
    )
    if photo_data is not None:
        try:
            new_student.photo_path = store_photo("students", student_id, *photo_data)
        except (UploadError, OSError):
            return _error("No se pudo guardar la foto")

    db.add(new_student)
    db.flush()
    add_audit(
        db,
        action="student.created",
        actor_id=request.state.user.id,
        entity_type="student",
        entity_id=new_student.id,
        details={
            "student_id": new_student.student_id,
            "is_authorized": bool(new_student.is_authorized),
        },
        request=request,
    )
    db.commit()
    return RedirectResponse(url="/students", status_code=303)


@router.post("/delete/{id}")
def delete_student(id: int, request: Request, db: Session = Depends(database.get_db)):
    student = db.query(models.Student).filter(models.Student.id == id).first()
    if not student:
        return _error("Estudiante no encontrado")

    lunch_count = db.query(models.LunchLog).filter(models.LunchLog.student_id == id).count()
    exit_count = db.query(models.ExitLog).filter(models.ExitLog.student_id == id).count()
    scan_count = db.query(models.ScanAttempt).filter(models.ScanAttempt.student_id == id).count()
    has_history = lunch_count > 0 or exit_count > 0 or scan_count > 0

    student_label = student.student_id
    if has_history:
        student.is_active = False
        action = "student.deactivated"
        message = "Estudiante desactivado para conservar el historial"
    else:
        db.delete(student)
        action = "student.deleted"
        message = "Estudiante eliminado"

    add_audit(
        db,
        action=action,
        actor_id=request.state.user.id,
        entity_type="student",
        entity_id=id,
        details={
            "student_id": student_label,
            "lunch_records": lunch_count,
            "exit_records": exit_count,
            "scan_records": scan_count,
        },
        request=request,
    )
    db.commit()
    return RedirectResponse(url=f"/students?msg={quote_plus(message)}", status_code=303)


@router.post("/toggle_auth/{id}")
def toggle_auth(id: int, request: Request, db: Session = Depends(database.get_db)):
    student = db.query(models.Student).filter(models.Student.id == id).first()
    if student:
        previous = bool(student.is_authorized)
        student.is_authorized = not previous
        add_audit(
            db,
            action="student.authorization_changed",
            actor_id=request.state.user.id,
            entity_type="student",
            entity_id=student.id,
            details={
                "student_id": student.student_id,
                "previous": previous,
                "new": bool(student.is_authorized),
            },
            request=request,
        )
        db.commit()
    return RedirectResponse(url="/students", status_code=303)


# --- IMPORTACIÓN EXCEL ---


@router.get("/template")
def download_template():
    return build_xlsx(
        filename="plantilla_estudiantes.xlsx",
        sheet_name="Plantilla",
        headers=["ID", "Nombre Completo", "Curso", "Autorizado (SI/NO)"],
        rows=[],
    )


@router.post("/import")
def import_students(
    request: Request, file: UploadFile = File(...), db: Session = Depends(database.get_db)
):
    if not (file.filename or "").lower().endswith((".xls", ".xlsx")):
        return _error("Formato inválido")

    try:
        contents = read_upload(file)
    except UploadError as exc:
        return _error(str(exc))

    try:
        df = read_excel(contents)
        count = 0
        skipped = 0
        for _, row in df.iterrows():
            sid = normalize_excel_id(row.iloc[0])
            name = clean_text(row.iloc[1])
            course = clean_text(row.iloc[2])
            if not sid or not name or not course:
                skipped += 1
                continue
            auth_val = clean_text(row.iloc[3]).upper()
            is_auth = auth_val in ["SI", "YES", "TRUE", "1"]

            existing = db.query(models.Student).filter(models.Student.student_id == sid).first()
            if existing:
                existing.full_name = name
                existing.course = course
                existing.is_authorized = is_auth
            else:
                new_student = models.Student(
                    student_id=sid, full_name=name, course=course, is_authorized=is_auth
                )
                db.add(new_student)
            count += 1

        add_audit(
            db,
            action="students.imported",
            actor_id=request.state.user.id,
            entity_type="student",
            details={"processed": count, "skipped": skipped, "filename": file.filename},
            request=request,
        )
        db.commit()
        message = f"Procesados+{count}+registros"
        if skipped:
            message += f"+({skipped}+omitidos)"
        return RedirectResponse(url=f"/students?msg={message}", status_code=303)
    except Exception:
        return RedirectResponse(url="/students?error=Error+al+procesar+archivo", status_code=303)


# --- IMPORTACIÓN MASIVA DE FOTOS (ZIP) ---


@router.post("/import-photos")
def import_photos_zip(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
):
    if not (file.filename or "").lower().endswith(".zip"):
        return _error("Debe ser un archivo ZIP")

    try:
        photos = zip_photo_entries(file)
    except UploadError as exc:
        return _error(str(exc))
    except (OSError, ValueError):
        return _error("Error al procesar el ZIP")

    processed_count = 0
    skipped = 0
    for stem, data, suffix in photos:
        student_id = normalize_excel_id(stem)
        if not student_id:
            skipped += 1
            continue

        student = db.query(models.Student).filter(models.Student.student_id == student_id).first()
        if not student:
            skipped += 1
            continue

        try:
            student.photo_path = store_photo("students", student_id, data, suffix)
        except (UploadError, OSError):
            skipped += 1
            continue
        processed_count += 1

    add_audit(
        db,
        action="students.photos_imported",
        actor_id=request.state.user.id,
        entity_type="student",
        details={
            "processed": processed_count,
            "skipped": skipped,
            "filename": file.filename,
        },
        request=request,
    )
    db.commit()
    message = f"Fotos actualizadas: {processed_count}"
    if skipped:
        message += f" ({skipped} omitidas)"
    return RedirectResponse(url=f"/students?msg={quote_plus(message)}", status_code=303)


# --- ACTUALIZACIONES ESPECÍFICAS (ALMUERZOS / RFID) ---


@router.post("/update-lunch-groups")
def update_lunch_groups_students(
    request: Request, file: UploadFile = File(...), db: Session = Depends(database.get_db)
):
    """
    Excel: Col 0 -> Student ID, Col 1 -> Grupos (Texto)
    Busca 'ALMUERZO NORMAL' o 'ALMUERZO ESPECIAL'
    """
    if not (file.filename or "").lower().endswith((".xls", ".xlsx")):
        return _error("Formato inválido")
    try:
        content = read_upload(file)
        df = read_excel(content)
        updated = 0
        skipped = 0

        for _, row in df.iterrows():
            sid = normalize_excel_id(row.iloc[0])
            if not sid:
                skipped += 1
                continue
            raw_groups = clean_text(row.iloc[1]).upper()

            student = db.query(models.Student).filter(models.Student.student_id == sid).first()
            if student:
                # Logica de asignación estricta según requerimiento
                if "ALMUERZO NORMAL" in raw_groups:
                    student.has_lunch = True
                    student.lunch_type = models.LunchType.NORMAL.value
                elif "ALMUERZO ESPECIAL" in raw_groups:
                    student.has_lunch = True
                    student.lunch_type = models.LunchType.ESPECIAL.value
                else:
                    # Si no está en el texto, se quita el permiso
                    student.has_lunch = False
                    student.lunch_type = models.LunchType.NONE.value
                updated += 1

        add_audit(
            db,
            action="students.lunch_groups_imported",
            actor_id=request.state.user.id,
            entity_type="student",
            details={"updated": updated, "skipped": skipped, "filename": file.filename},
            request=request,
        )
        db.commit()
        return RedirectResponse(f"/students?msg=Almuerzos+actualizados:+{updated}", 303)
    except Exception:
        return RedirectResponse("/students?error=Error+procesando+archivo", 303)


@router.post("/update-rfid")
def update_rfid_students(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
):
    """Excel: Col 0 -> Student ID, Col 1 -> RFID Code"""
    if not (file.filename or "").lower().endswith((".xls", ".xlsx")):
        return _error("Formato inválido")
    try:
        df = read_excel(read_upload(file))
        updated = 0
        skipped = 0
        seen_rfid: set[str] = set()
        for _, row in df.iterrows():
            sid = normalize_excel_id(row.iloc[0])
            rfid = normalize_rfid(row.iloc[1])
            if not sid or not rfid:
                skipped += 1
                continue

            student = db.query(models.Student).filter(models.Student.student_id == sid).first()
            if not student or rfid in seen_rfid:
                skipped += 1
                continue
            duplicate = (
                db.query(models.Student)
                .filter(
                    models.Student.rfid_code == rfid,
                    models.Student.id != student.id,
                )
                .first()
            )
            if duplicate:
                skipped += 1
                continue

            seen_rfid.add(rfid)
            student.rfid_code = rfid
            updated += 1
        add_audit(
            db,
            action="students.rfid_imported",
            actor_id=request.state.user.id,
            entity_type="student",
            details={"updated": updated, "skipped": skipped, "filename": file.filename},
            request=request,
        )
        db.commit()
        message = f"RFIDs actualizados: {updated}"
        if skipped:
            message += f" ({skipped} omitidos)"
        return RedirectResponse(f"/students?msg={quote_plus(message)}", 303)
    except Exception:
        return _error("Error al procesar el archivo")
