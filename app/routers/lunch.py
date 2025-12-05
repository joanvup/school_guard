from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import cast, Date, desc, or_
from datetime import datetime
import pytz
from .. import database, models, deps, auth
import pandas as pd
import io


router = APIRouter(
    prefix="/lunch",
    tags=["Lunch Control"],
    dependencies=[Depends(deps.require_lunch_access)] # Solo Admin y Operador Almuerzo
)

templates = Jinja2Templates(directory="app/templates")
TZ_COLOMBIA = pytz.timezone('America/Bogota')

@router.get("/scan")
def lunch_scan_view(request: Request):
    return templates.TemplateResponse("lunch_scan.html", {
        "request": request,
        "user": request.state.user
    })

@router.get("/search_person")
def search_person_for_lunch(q: str = Query(..., min_length=3), db: Session = Depends(database.get_db)):
    """Busca estudiantes o empleados por nombre para selección manual"""
    search_pattern = f"%{q}%"
    
    # Buscar Estudiantes (Límite 5 para no saturar)
    students = db.query(models.Student).filter(
        models.Student.full_name.like(search_pattern)
    ).limit(5).all()
    
    # Buscar Empleados (Límite 5)
    employees = db.query(models.Employee).filter(
        models.Employee.full_name.like(search_pattern)
    ).limit(5).all()
    
    results = []
    
    for s in students:
        results.append({
            "code": s.student_id, # Esto es lo que enviaremos a process_lunch
            "name": s.full_name,
            "type": "Estudiante",
            "extra": s.course,
            "photo": s.photo_path
        })
        
    for e in employees:
        results.append({
            "code": e.doc_id,
            "name": e.full_name,
            "type": "Empleado",
            "extra": e.position or "General",
            "photo": e.photo_path
        })
        
    return results

@router.post("/process")
async def process_lunch(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    raw_code = data.get("code", "").strip() # Puede ser QR firmado o RFID plano
    
    if not raw_code:
        return JSONResponse({"status": "error", "message": "Código vacío"})

    # 1. INTENTAR IDENTIFICAR PERSONA
    person = None
    person_type = None # 'student' | 'employee'
    
    # A. Verificación QR Firmado (Si tiene punto, asumimos formato ID.FIRMA)
    clean_id = auth.verify_qr_content(raw_code)
    
    if clean_id:
        # Es un QR válido, buscamos por ID visual (student_id / doc_id)
        # Primero Estudiante
        person = db.query(models.Student).filter(models.Student.student_id == clean_id).first()
        if person: 
            person_type = 'student'
        else:
            # Luego Empleado
            person = db.query(models.Employee).filter(models.Employee.doc_id == clean_id).first()
            if person: person_type = 'employee'
    else:
        # B. Es RFID o Entrada Manual (No tiene firma o firma inválida, lo tratamos como raw)
        # Buscamos por rfid_code O por ID visual directo (para teclado manual)
        
        # 1. Estudiante
        person = db.query(models.Student).filter(
            (models.Student.rfid_code == raw_code) | (models.Student.student_id == raw_code)
        ).first()
        
        if person:
            person_type = 'student'
        else:
            # 2. Empleado
            person = db.query(models.Employee).filter(
                (models.Employee.rfid_code == raw_code) | (models.Employee.doc_id == raw_code)
            ).first()
            if person: person_type = 'employee'

    # SI NO SE ENCUENTRA
    if not person:
        return JSONResponse(content={"status": "error", "message": "NO ENCONTRADO O NO REGISTRADO"})

    # 2. VALIDAR AUTORIZACIÓN DE ALMUERZO
    if not person.has_lunch:
        return JSONResponse(content={
            "status": "denied",
            "message": "NO TIENE ALMUERZO ASIGNADO",
            "person": {
                "name": person.full_name,
                "photo": person.photo_path,
                "type": "Estudiante" if person_type == 'student' else "Empleado"
            }
        })

    # Pre-calcular info extra (Curso o Cargo) para usarla en las respuestas
    extra_info = person.course if person_type == 'student' else (person.position or 'Empleado')
    # 3. VERIFICAR DUPLICIDAD (YA COMIÓ HOY?)
    now_co = datetime.now(TZ_COLOMBIA)
    today_date = now_co.date()
    
    query_log = db.query(models.LunchLog).filter(
        cast(models.LunchLog.timestamp, Date) == today_date
    )
    
    if person_type == 'student':
        query_log = query_log.filter(models.LunchLog.student_id == person.id)
    else:
        query_log = query_log.filter(models.LunchLog.employee_id == person.id)
        
    existing_log = query_log.first()
    
    if existing_log:
        return JSONResponse(content={
            "status": "warning",
            "message": f"YA RECLAMÓ ALMUERZO A LAS {existing_log.timestamp.strftime('%I:%M %p')}",
            "lunch_type": person.lunch_type, # Enviamos el tipo para mostrarlo en grande
            "person": {
                "name": person.full_name,
                "photo": person.photo_path,
                "type": "Estudiante" if person_type == 'student' else "Empleado",
                "extra": extra_info # Enviamos el cargo/curso
            }
        })

    # 4. REGISTRAR ENTREGA
    operator_id = request.state.user.id if request.state.user else 1
    
    # Manejar el tipo de almuerzo (asegurar que guardamos el string)
    # En modelo Employee es String, en Student ahora es String (según cambio parte anterior)
    lunch_val = person.lunch_type 
    
    new_log = models.LunchLog(
        student_id=person.id if person_type == 'student' else None,
        employee_id=person.id if person_type == 'employee' else None,
        operator_id=operator_id,
        timestamp=now_co,
        delivered_type=lunch_val
    )
    db.add(new_log)
    db.commit()

    # 5. RETORNAR ÉXITO Y DATOS PARA IMPRESIÓN
    # Preparamos datos extra (Curso o Cargo)
    extra_info = person.course if person_type == 'student' else (person.position or 'Empleado')

    return JSONResponse(content={
        "status": "success",
        "message": "ALMUERZO AUTORIZADO",
        "lunch_type": lunch_val, # NORMAL o ESPECIAL
        "timestamp": now_co.strftime("%Y-%m-%d %H:%M:%S"),
        "person": {
            "name": person.full_name,
            "photo": person.photo_path,
            "type": "Estudiante" if person_type == 'student' else "Empleado",
            "extra": extra_info
        },
        # Datos crudos para que el Frontend genere el ticket de impresión
        "ticket_data": {
            "name": person.full_name,
            "type": lunch_val,
            "extra": extra_info,
            "date": now_co.strftime("%Y-%m-%d"),
            "time": now_co.strftime("%I:%M %p")
        }
    })

# --- REPORTES ---

@router.get("/reports")
def lunch_reports_view(
    request: Request,
    date_start: str = Query(None),
    date_end: str = Query(None),
    lunch_type: str = Query(None), # Normal, Especial
    person_type: str = Query(None), # student, employee
    db: Session = Depends(database.get_db)
):
    now = datetime.now(TZ_COLOMBIA)
    if not date_start: date_start = now.strftime('%Y-%m-%d')
    if not date_end: date_end = now.strftime('%Y-%m-%d')

    start_dt = datetime.strptime(date_start, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
    end_dt = datetime.strptime(date_end, '%Y-%m-%d').replace(hour=23, minute=59, second=59)

    query = db.query(models.LunchLog).filter(models.LunchLog.timestamp >= start_dt, models.LunchLog.timestamp <= end_dt)

    if lunch_type and lunch_type != "Todos":
        query = query.filter(models.LunchLog.delivered_type == lunch_type)
    
    if person_type:
        if person_type == "student":
            query = query.filter(models.LunchLog.student_id != None)
        elif person_type == "employee":
            query = query.filter(models.LunchLog.employee_id != None)

    logs = query.order_by(models.LunchLog.timestamp.desc()).all()
    
    # KPIs rápidos
    total_normal = 0
    total_special = 0
    for l in logs:
        if l.delivered_type == "Normal": total_normal += 1
        elif l.delivered_type == "Especial": total_special += 1

    return templates.TemplateResponse("lunch_reports.html", {
        "request": request, "user": request.state.user, "logs": logs,
        "filters": {"date_start": date_start, "date_end": date_end, "lunch_type": lunch_type, "person_type": person_type},
        "stats": {"normal": total_normal, "special": total_special, "total": len(logs)}
    })

@router.get("/reports/export")
def export_lunch_excel(
    date_start: str = Query(...),
    date_end: str = Query(...),
    lunch_type: str = Query(None),
    person_type: str = Query(None),
    db: Session = Depends(database.get_db)
):
    # (Misma lógica de filtrado que arriba)
    start_dt = datetime.strptime(date_start, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
    end_dt = datetime.strptime(date_end, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    query = db.query(models.LunchLog).filter(models.LunchLog.timestamp >= start_dt, models.LunchLog.timestamp <= end_dt)

    if lunch_type and lunch_type != "Todos": query = query.filter(models.LunchLog.delivered_type == lunch_type)
    if person_type == "student": query = query.filter(models.LunchLog.student_id != None)
    elif person_type == "employee": query = query.filter(models.LunchLog.employee_id != None)
    
    logs = query.all()
    
    data = []
    for log in logs:
        # Determinar nombre y tipo
        if log.student:
            name = log.student.full_name
            p_type = "Estudiante"
            extra = log.student.course
        elif log.employee:
            name = log.employee.full_name
            p_type = "Empleado"
            extra = log.employee.position
        else:
            name = "Desconocido"
            p_type = "?"
            extra = ""

        data.append({
            "Fecha": log.timestamp.strftime("%Y-%m-%d"),
            "Hora": log.timestamp.strftime("%H:%M:%S"),
            "Tipo Almuerzo": log.delivered_type,
            "Nombre": name,
            "Tipo Persona": p_type,
            "Curso/Cargo": extra,
            "Operador": log.operator.username
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Almuerzos')
    output.seek(0)
    
    headers = {'Content-Disposition': f'attachment; filename="almuerzos_{date_start}.xlsx"'}
    return Response(content=output.getvalue(), headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')