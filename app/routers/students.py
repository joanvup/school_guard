from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException, Response
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
def list_students(request: Request, db: Session = Depends(database.get_db)):
    # Ordenar por fecha de creación descendente para ver los nuevos primero
    students = db.query(models.Student).order_by(models.Student.created_at.desc()).all()
    return templates.TemplateResponse("students.html", {"request": request, "students": students, "user": request.state.user})

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
    if student:
        # Opcional: Borrar foto del disco si se desea
        # if student.photo_path:
        #     try: os.remove(f"app{student.photo_path}")
        #     except: pass
        db.delete(student)
        db.commit()
    return RedirectResponse(url="/students", status_code=303)

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