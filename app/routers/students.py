from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException, Response, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List, Optional
import pandas as pd
import io
import os
import shutil
import zipfile 
from .. import database, models, schemas, deps
from starlette.requests import Request
import math
from sqlalchemy import or_

router = APIRouter(
    prefix="/students",
    tags=["Students"],
    dependencies=[Depends(deps.require_admin)]
)

templates = Jinja2Templates(directory="app/templates")
PHOTOS_DIR = "app/static/photos"

# Asegurar que el directorio existe
os.makedirs(PHOTOS_DIR, exist_ok=True)

# --- VISTAS ---

@router.get("/")
def list_students(
    request: Request, 
    page: int = Query(1, ge=1), # Página actual, defecto 1
    q: str = Query(None),       # Término de búsqueda
    db: Session = Depends(database.get_db)
):
    LIMIT = 10 # Cantidad de estudiantes por página
    
    # Consulta base
    query = db.query(models.Student)
    
    # Aplicar búsqueda si existe
    if q:
        search_fmt = f"%{q}%"
        # Busca por Nombre O por ID
        query = query.filter(
            or_(
                models.Student.full_name.ilike(search_fmt),
                models.Student.student_id.ilike(search_fmt)
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
    
    return templates.TemplateResponse("students.html", {
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
            "q": q or "" # Devolver el término de búsqueda para mantenerlo en el input
        }
    })
# --- API / ACCIONES ---

@router.post("/create")
async def create_student(
    student_id: str = Form(...),
    full_name: str = Form(...),
    course: str = Form(...),
    is_authorized: bool = Form(False),
    photo: Optional[UploadFile] = File(None), # Campo opcional
    db: Session = Depends(database.get_db)
):
    # Verificar duplicados
    if db.query(models.Student).filter(models.Student.student_id == student_id).first():
        return RedirectResponse(url="/students?msg=Error:+ID+Duplicado", status_code=303)

    photo_path = None
    
    # Procesar foto individual si se subió
    if photo and photo.filename:
        # Guardamos la foto con el nombre del ID para mantener orden: 202301.jpg
        extension = photo.filename.split(".")[-1].lower()
        if extension not in ["jpg", "jpeg", "png"]:
             return RedirectResponse(url="/students?error=Solo+imagenes+JPG/PNG", status_code=303)
        
        filename = f"{student_id}.{extension}"
        file_location = os.path.join(PHOTOS_DIR, filename)
        
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        
        # Ruta relativa para guardar en BD
        photo_path = f"/static/photos/{filename}"

    new_student = models.Student(
        student_id=student_id,
        full_name=full_name,
        course=course,
        is_authorized=is_authorized,
        photo_path=photo_path
    )
    db.add(new_student)
    db.commit()
    return RedirectResponse(url="/students", status_code=303)

@router.get("/delete/{id}")
def delete_student(id: int, db: Session = Depends(database.get_db)):
    student = db.query(models.Student).filter(models.Student.id == id).first()
    if not student:
        return RedirectResponse(url="/students?error=Estudiante+no+encontrado", status_code=303)

    # 1. Verificar Historial de Almuerzos
    lunch_count = db.query(models.LunchLog).filter(models.LunchLog.student_id == id).count()
    if lunch_count > 0:
        return RedirectResponse(
            url="/students?error=Error:+El+estudiante+tiene+historial+de+almuerzos.", 
            status_code=303
        )

    # 2. Verificar Historial de Salidas
    exit_count = db.query(models.ExitLog).filter(models.ExitLog.student_id == id).count()
    if exit_count > 0:
        return RedirectResponse(
            url="/students?error=Error:+El+estudiante+tiene+historial+de+salidas.", 
            status_code=303
        )

    # Si está limpio, borrar
    db.delete(student)
    db.commit()
    return RedirectResponse(url="/students?msg=Estudiante+eliminado", status_code=303)

@router.get("/toggle_auth/{id}")
def toggle_auth(id: int, db: Session = Depends(database.get_db)):
    student = db.query(models.Student).filter(models.Student.id == id).first()
    if student:
        student.is_authorized = not student.is_authorized
        db.commit()
    return RedirectResponse(url="/students", status_code=303)

# --- IMPORTACIÓN EXCEL ---

@router.get("/template")
def download_template():
    df = pd.DataFrame(columns=["ID", "Nombre Completo", "Curso", "Autorizado (SI/NO)"])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Plantilla')
    output.seek(0)
    headers = {'Content-Disposition': 'attachment; filename="plantilla_estudiantes.xlsx"'}
    return Response(content=output.getvalue(), headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@router.post("/import")
async def import_students(file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    if not file.filename.endswith(('.xls', '.xlsx')):
        return RedirectResponse(url="/students?error=Formato+invalido", status_code=303)
    
    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
        count = 0
        for _, row in df.iterrows():
            sid = str(row[0]).strip()
            name = str(row[1]).strip()
            course = str(row[2]).strip()
            auth_val = str(row[3]).upper()
            is_auth = True if auth_val in ['SI', 'YES', 'TRUE', '1'] else False
            
            existing = db.query(models.Student).filter(models.Student.student_id == sid).first()
            if existing:
                existing.full_name = name
                existing.course = course
                existing.is_authorized = is_auth
            else:
                new_student = models.Student(student_id=sid, full_name=name, course=course, is_authorized=is_auth)
                db.add(new_student)
            count += 1
        
        db.commit()
        return RedirectResponse(url=f"/students?msg=Procesados+{count}+registros", status_code=303)
    except Exception as e:
        print(e)
        return RedirectResponse(url="/students?error=Error+al+procesar+archivo", status_code=303)

# --- IMPORTACIÓN MASIVA DE FOTOS (ZIP) ---

@router.post("/import-photos")
async def import_photos_zip(file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    if not file.filename.endswith('.zip'):
        return RedirectResponse(url="/students?error=Debe+ser+un+archivo+ZIP", status_code=303)

    try:
        content = await file.read()
        zip_buffer = io.BytesIO(content)
        
        processed_count = 0
        
        with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
            # Obtener lista de archivos en el ZIP
            for file_name in zip_ref.namelist():
                # Ignorar carpetas o archivos ocultos (__MACOSX, etc)
                if file_name.startswith("__") or file_name.endswith("/"):
                    continue
                
                # Extraer nombre base (ID) y extensión
                # Ejemplo: "fotos/1001.jpg" -> "1001.jpg"
                base_name = os.path.basename(file_name) 
                name_parts = os.path.splitext(base_name)
                
                if len(name_parts) < 2: continue
                
                student_id = name_parts[0] # El ID es el nombre del archivo
                ext = name_parts[1].lower()
                
                if ext not in ['.jpg', '.jpeg', '.png']:
                    continue
                
                # Buscar estudiante por ID
                student = db.query(models.Student).filter(models.Student.student_id == student_id).first()
                
                if student:
                    # Guardar archivo
                    target_filename = f"{student_id}{ext}"
                    target_path = os.path.join(PHOTOS_DIR, target_filename)
                    
                    with open(target_path, "wb") as f:
                        f.write(zip_ref.read(file_name))
                    
                    # Actualizar BD
                    student.photo_path = f"/static/photos/{target_filename}"
                    processed_count += 1
        
        db.commit()
        return RedirectResponse(url=f"/students?msg=Fotos+actualizadas:+{processed_count}", status_code=303)

    except Exception as e:
        print(f"Error ZIP: {e}")
        return RedirectResponse(url="/students?error=Error+al+procesar+ZIP", status_code=303)

# --- ACTUALIZACIONES ESPECÍFICAS (ALMUERZOS / RFID) ---

@router.post("/update-lunch-groups")
async def update_lunch_groups_students(file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    """
    Excel: Col 0 -> Student ID, Col 1 -> Grupos (Texto)
    Busca 'ALMUERZO NORMAL' o 'ALMUERZO ESPECIAL'
    """
    print("mola")
    if not file.filename.endswith(('.xls', '.xlsx')): 
        return RedirectResponse("/students?error=Formato+invalido", 303)
    try:
        content = await file.read()
        df = pd.read_excel(io.BytesIO(content))
        updated = 0
        
        for _, row in df.iterrows():
            sid = str(row[0]).strip()
            # Asegurar que grupos no sea NaN
            raw_groups = str(row[1]).upper() if pd.notna(row[1]) else ""
            
            student = db.query(models.Student).filter(models.Student.student_id == sid).first()
            if student:
                # Logica de asignación estricta según requerimiento
                if "ALMUERZO NORMAL" in raw_groups:
                    student.has_lunch = True
                    student.lunch_type = models.LunchType.NORMAL
                elif "ALMUERZO ESPECIAL" in raw_groups:
                    student.has_lunch = True
                    student.lunch_type = models.LunchType.ESPECIAL
                else:
                    # Si no está en el texto, se quita el permiso
                    student.has_lunch = False
                    student.lunch_type = models.LunchType.NONE
                updated += 1
        
        db.commit()
        return RedirectResponse(f"/students?msg=Almuerzos+actualizados:+{updated}", 303)
    except Exception as e:
        print(e)
        return RedirectResponse("/students?error=Error+procesando+archivo", 303)

@router.post("/update-rfid")
async def update_rfid_students(file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    """Excel: Col 0 -> Student ID, Col 1 -> RFID Code"""
    if not file.filename.endswith(('.xls', '.xlsx')): 
        return RedirectResponse("/students?error=Formato+invalido", 303)
    try:
        df = pd.read_excel(io.BytesIO(await file.read()))
        updated = 0
        for _, row in df.iterrows():
            sid = str(row[0]).strip()
            rfid = str(row[1]).strip()
            if rfid.endswith('.0'): rfid = rfid[:-2]

            student = db.query(models.Student).filter(models.Student.student_id == sid).first()
            if student:
                student.rfid_code = rfid
                updated += 1
        db.commit()
        return RedirectResponse(f"/students?msg=RFIDs+actualizados:+{updated}", 303)
    except Exception: return RedirectResponse("/students?error=Error+archivo", 303)