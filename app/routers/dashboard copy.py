from fastapi import APIRouter, Depends, Request, Query
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, cast, Date
from datetime import datetime
import pytz
from .. import database, models, deps

router = APIRouter(dependencies=[Depends(deps.require_user)])
templates = Jinja2Templates(directory="app/templates")
TZ_COLOMBIA = pytz.timezone('America/Bogota')

@router.get("/dashboard")
def dashboard_view(request: Request, db: Session = Depends(database.get_db)):
    # 1. Calcular fecha actual en Colombia
    now = datetime.now(TZ_COLOMBIA)
    today_date = now.date() # Solo la fecha: 2023-10-27
    
    # 2. Consulta Base: Logs de HOY
    # Usamos cast(..., Date) para comparar solo fecha y evitar problemas de horas UTC vs Local
    logs_today_query = db.query(models.ExitLog).filter(
        cast(models.ExitLog.timestamp, Date) == today_date
    )
    
    exits_today_count = logs_today_query.count()
    total_students = db.query(models.Student).count()
    
    # 3. Salidas por Puerta (Datos para la lista y gráfica)
    # Agrupamos directamente en SQL: SELECT door_id, COUNT(*) FROM logs ... GROUP BY door_id
    doors_aggs = db.query(models.Door, func.count(models.ExitLog.id))\
        .join(models.ExitLog, models.Door.id == models.ExitLog.door_id)\
        .filter(cast(models.ExitLog.timestamp, Date) == today_date)\
        .group_by(models.Door.id).all()
    
    # Transformar a formato amigable
    # Primero obtenemos TODAS las puertas activas para mostrar incluso las que tienen 0
    all_doors = db.query(models.Door).filter(models.Door.is_active == True).all()
    doors_stats = []
    
    # Mapa temporal de conteos {door_id: count}
    counts_map = {door.id: count for door, count in doors_aggs}
    
    for door in all_doors:
        count = counts_map.get(door.id, 0)
        percent = 0
        if exits_today_count > 0:
            percent = round((count / exits_today_count) * 100, 1)
            
        doors_stats.append({
            "id": door.id,
            "name": door.name,
            "count": count,
            "percent": percent
        })
    
    # Ordenar mayor a menor
    doors_stats.sort(key=lambda x: x['count'], reverse=True)

    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "user": request.state.user,
        "stats": {
            "total_students": total_students,
            "exits_today": exits_today_count,
            "doors_data": doors_stats
        }
    })

@router.get("/api/dashboard/details")
def get_dashboard_details(
    type: str = Query(..., regex="^(all|door)$"), 
    id: int = Query(None), 
    db: Session = Depends(database.get_db)
):
    now = datetime.now(TZ_COLOMBIA)
    today_date = now.date()
    
    query = db.query(models.ExitLog).filter(
        cast(models.ExitLog.timestamp, Date) == today_date
    )
    
    if type == 'door' and id:
        query = query.filter(models.ExitLog.door_id == id)
        
    logs = query.order_by(models.ExitLog.timestamp.desc()).all()
    
    data = []
    for log in logs:
        # Asegurar visualización correcta de hora
        ts = log.timestamp
        # Si la BD devuelve UTC plano, ajustamos visualmente (opcional, depende del driver)
        # Para simplificar, asumimos que el objeto datetime tiene la info correcta o es UTC
        display_time = ts.strftime("%I:%M:%S %p")
        
        data.append({
            "photo": log.student.photo_path,
            "name": log.student.full_name,
            "course": log.student.course,
            "time": display_time,
            "door": log.door.name
        })
    return data

@router.get("/api/dashboard/chart-data")
def get_chart_data(db: Session = Depends(database.get_db)):
    now = datetime.now(TZ_COLOMBIA)
    today_date = now.date()

    # --- DATOS GRÁFICA 1: CURSOS (PIE) ---
    courses_data = db.query(models.Student.course, func.count(models.ExitLog.id))\
        .join(models.ExitLog)\
        .filter(cast(models.ExitLog.timestamp, Date) == today_date)\
        .group_by(models.Student.course).all()
    
    labels_courses = []
    values_courses = []
    
    if not courses_data:
        # Si no hay datos, enviar placeholders vacíos para que chartjs no falle
        labels_courses = ["Sin datos"]
        values_courses = [0]
    else:
        labels_courses = [str(d[0]) for d in courses_data]
        values_courses = [d[1] for d in courses_data]

    # --- DATOS GRÁFICA 2: LINEA DE TIEMPO ---
    # Obtenemos todos los timestamps de hoy
    logs_today = db.query(models.ExitLog.timestamp).filter(
        cast(models.ExitLog.timestamp, Date) == today_date
    ).all()
    
    hours_map = {h: 0 for h in range(6, 19)} # 6am a 6pm
    
    for log in logs_today:
        ts = log.timestamp
        # Truco sucio pero efectivo: si la hora es muy distinta a Colombia, ajustar manual
        # O confiar en que pytz lo hace si el modelo tiene timezone=True
        h = ts.hour 
        # Ajuste manual simple si tus logs salen con +5 horas (ej, 10am aparece como 15pm)
        # if h > 12: h = h - 5 (Solo si notas desfase, por ahora lo dejo nativo)
        
        if h in hours_map:
            hours_map[h] += 1
            
    labels_hours = [f"{h}:00" for h in sorted(hours_map.keys())]
    values_hours = [hours_map[h] for h in sorted(hours_map.keys())]

    return {
        "courses": {"labels": labels_courses, "data": values_courses},
        "timeline": {"labels": labels_hours, "data": values_hours}
    }