from fastapi import APIRouter, Depends, Form, UploadFile, File, Response, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
import pandas as pd
import io
import math
import os
import shutil
from typing import Optional
from .. import database, models, deps

router = APIRouter(
    prefix="/employees",
    tags=["Employees"],
    dependencies=[Depends(deps.require_admin)]
)

templates = Jinja2Templates(directory="app/templates")
PHOTOS_DIR = "app/static/photos"

# --- VISTA LISTADO ---
@router.get("/")
def list_employees(
    request: Request, 
    page: int = 1, 
    search: str = "", 
    db: Session = Depends(database.get_db)
):
    limit = 20
    query = db.query(models.Employee)
    
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(or_(
            models.Employee.full_name.like(search_pattern),
            models.Employee.doc_id.like(search_pattern)
        ))
    
    total_records = query.count()
    total_pages = math.ceil(total_records / limit)
    
    if page < 1: page = 1
    if page > total_pages and total_pages > 0: page = total_pages
    offset = (page - 1) * limit
    
    employees = query.order_by(models.Employee.full_name.asc()).offset(offset).limit(limit).all()
    
    return templates.TemplateResponse("employees.html", {
        "request": request, 
        "employees": employees, 
        "page": page, "total_pages": total_pages, "search": search,
        "user": request.state.user
    })

# --- ACCIONES CRUD ---

@router.post("/create")
def create_employee(
    doc_id: str = Form(...),
    full_name: str = Form(...),
    position: str = Form(None),
    has_lunch: bool = Form(False),
    lunch_type: str = Form("Normal"), # Viene como texto: "Normal" o "Especial"
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(database.get_db)
):
    if db.query(models.Employee).filter(models.Employee.doc_id == doc_id).first():
        return RedirectResponse(url="/employees?error=Cédula+ya+existe", status_code=303)
    
    photo_path = None
    if photo and photo.filename:
        ext = photo.filename.split(".")[-1].lower()
        if ext in ["jpg", "jpeg", "png"]:
            filename = f"EMP_{doc_id}.{ext}"
            file_location = os.path.join(PHOTOS_DIR, filename)
            with open(file_location, "wb") as buffer:
                shutil.copyfileobj(photo.file, buffer)
            photo_path = f"/static/photos/{filename}"

    # --- CORRECCIÓN AQUÍ ---
    # Convertimos el string "Normal" al objeto Enum <LunchType.NORMAL>
    try:
        enum_obj = models.LunchType(lunch_type)
        lunch_value = enum_obj.value # Extraemos "Normal" o "Especial"
    except ValueError:
        # Si por alguna razón llega un valor raro, asignamos NONE o NORMAL por defecto
        lunch_value = "Ninguno"

    new_emp = models.Employee(
        doc_id=doc_id, 
        full_name=full_name, 
        position=position,
        has_lunch=has_lunch, 
        lunch_type=lunch_value,
        photo_path=photo_path
    )
    db.add(new_emp)
    db.commit()
    return RedirectResponse(url="/employees?msg=Empleado+creado", status_code=303)

@router.get("/delete/{id}")
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
            status_code=303
        )
        
    # Si no tiene registros, procedemos a borrar
    db.delete(emp)
    db.commit()
    
    return RedirectResponse(url="/employees?msg=Empleado+eliminado", status_code=303)

# --- IMPORTACIONES ---

@router.post("/import-basic")
async def import_basic(file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    """Carga inicial de empleados (ID, Nombre, Cargo)"""
    if not file.filename.endswith(('.xls', '.xlsx')): return RedirectResponse("/employees?error=Formato+invalido", 303)
    try:
        df = pd.read_excel(io.BytesIO(await file.read()))
        count = 0
        for _, row in df.iterrows():
            did = str(row[0]).strip()
            name = str(row[1]).strip()
            pos = str(row[2]).strip() if len(row) > 2 else ""
            
            existing = db.query(models.Employee).filter(models.Employee.doc_id == did).first()
            if not existing:
                db.add(models.Employee(doc_id=did, full_name=name, position=pos))
                count += 1
        db.commit()
        return RedirectResponse(f"/employees?msg=Creados+{count}+empleados", 303)
    except Exception: return RedirectResponse("/employees?error=Error+archivo", 303)

@router.post("/update-lunch-groups")
async def update_lunch_groups(file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    """
    Actualiza permisos de almuerzo basado en columna 'grupos'.
    Logica: Busca 'ALMUERZO NORMAL' o 'ALMUERZO ESPECIAL'.
    """
    if not file.filename.endswith(('.xls', '.xlsx')): return RedirectResponse("/employees?error=Formato+invalido", 303)
    try:
        df = pd.read_excel(io.BytesIO(await file.read()))
        updated = 0
        
        # Asumimos Col 0: ID, Col 1: Grupos (Texto largo)
        for _, row in df.iterrows():
            did = str(row[0]).strip()
            raw_groups = str(row[1]).upper() # Convertir a mayúsculas para buscar
            
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
                    emp.lunch_type = models.LunchType.NONE
                updated += 1
        
        db.commit()
        return RedirectResponse(f"/employees?msg=Almuerzos+actualizados:+{updated}", 303)
    except Exception as e: 
        print(e)
        return RedirectResponse("/employees?error=Error+procesando+grupos", 303)

@router.post("/update-rfid")
async def update_rfid(file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    """Actualiza solo el código RFID. Col 0: ID, Col 1: RFID"""
    if not file.filename.endswith(('.xls', '.xlsx')): return RedirectResponse("/employees?error=Formato+invalido", 303)
    try:
        df = pd.read_excel(io.BytesIO(await file.read()))
        updated = 0
        for _, row in df.iterrows():
            did = str(row[0]).strip()
            rfid = str(row[1]).strip()
            # Limpieza básica de RFID (quitar decimales si excel lo pone como float)
            if rfid.endswith('.0'): rfid = rfid[:-2]

            emp = db.query(models.Employee).filter(models.Employee.doc_id == did).first()
            if emp:
                emp.rfid_code = rfid
                updated += 1
        db.commit()
        return RedirectResponse(f"/employees?msg=RFIDs+actualizados:+{updated}", 303)
    except Exception: return RedirectResponse("/employees?error=Error+archivo", 303)

@router.post("/update")
def update_employee(
    id: int = Form(...),
    doc_id: str = Form(...),
    full_name: str = Form(...),
    position: str = Form(None),
    has_lunch: bool = Form(False),
    lunch_type: str = Form("Normal"),
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(database.get_db)
):
    emp = db.query(models.Employee).filter(models.Employee.id == id).first()
    if not emp:
        return RedirectResponse(url="/employees?error=Empleado+no+encontrado", status_code=303)
    
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
            file_location = os.path.join(PHOTOS_DIR, filename)
            with open(file_location, "wb") as buffer:
                shutil.copyfileobj(photo.file, buffer)
            emp.photo_path = f"/static/photos/{filename}"

    db.commit()
    return RedirectResponse(url="/employees?msg=Empleado+actualizado", status_code=303)