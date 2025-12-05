from fastapi import APIRouter, Depends, Request, Query
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date
from datetime import datetime
import pytz
from .. import database, models, deps

router = APIRouter(dependencies=[Depends(deps.require_user)])
templates = Jinja2Templates(directory="app/templates")
TZ_COLOMBIA = pytz.timezone('America/Bogota')

# --- UTILIDAD ---
def get_date_obj(date_str: str = None):
    """Convierte string YYYY-MM-DD a objeto date. Si es None, devuelve HOY."""
    if date_str:
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    return datetime.now(TZ_COLOMBIA).date()

# --- VISTA HTML (Carga inicial) ---
@router.get("/dashboard")
def dashboard_view(request: Request, db: Session = Depends(database.get_db)):
    # Solo renderizamos la estructura, los datos se cargarán vía JS o 
    # pasamos la fecha de hoy para configurar el input.
    today = datetime.now(TZ_COLOMBIA).date()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "user": request.state.user,
        "today_date": today.strftime('%Y-%m-%d')
    })

# --- API ENDPOINTS (JSON) ---

@router.get("/api/dashboard/stats")
def get_dashboard_stats(
    date: str = Query(None), # Formato YYYY-MM-DD
    db: Session = Depends(database.get_db)
):
    target_date = get_date_obj(date)
    
    # 1. Total Salidas en la fecha
    exits_count = db.query(models.ExitLog).filter(
        cast(models.ExitLog.timestamp, Date) == target_date
    ).count()
    
    # 2. Total Estudiantes (Estatíco, no depende de la fecha, pero lo mandamos)
    total_students = db.query(models.Student).count()
    
    # 3. Estadísticas por Puerta (Lista)
    doors_aggs = db.query(models.Door, func.count(models.ExitLog.id))\
        .join(models.ExitLog, models.Door.id == models.ExitLog.door_id)\
        .filter(cast(models.ExitLog.timestamp, Date) == target_date)\
        .group_by(models.Door.id).all()
    
    all_doors = db.query(models.Door).filter(models.Door.is_active == True).all()
    doors_stats = []
    counts_map = {door.id: count for door, count in doors_aggs}
    
    for door in all_doors:
        count = counts_map.get(door.id, 0)
        percent = 0
        if exits_count > 0:
            percent = round((count / exits_count) * 100, 1)
            
        doors_stats.append({
            "id": door.id,
            "name": door.name,
            "count": count,
            "percent": percent
        })
    
    doors_stats.sort(key=lambda x: x['count'], reverse=True)

    return {
        "exits_count": exits_count,
        "total_students": total_students,
        "doors_data": doors_stats
    }

@router.get("/api/dashboard/details")
def get_dashboard_details(
    type: str = Query(..., regex="^(all|door)$"), 
    id: int = Query(None),
    date: str = Query(None), # Nuevo param
    db: Session = Depends(database.get_db)
):
    target_date = get_date_obj(date)
    
    query = db.query(models.ExitLog).filter(
        cast(models.ExitLog.timestamp, Date) == target_date
    )
    
    if type == 'door' and id:
        query = query.filter(models.ExitLog.door_id == id)
        
    logs = query.order_by(models.ExitLog.timestamp.desc()).all()
    
    data = []
    for log in logs:
        ts = log.timestamp
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
def get_chart_data(
    date: str = Query(None), # Nuevo param
    db: Session = Depends(database.get_db)
):
    target_date = get_date_obj(date)

    # Gráfica Cursos
    courses_data = db.query(models.Student.course, func.count(models.ExitLog.id))\
        .join(models.ExitLog)\
        .filter(cast(models.ExitLog.timestamp, Date) == target_date)\
        .group_by(models.Student.course).all()
    
    labels_courses = []
    values_courses = []
    if not courses_data:
        labels_courses = ["Sin datos"]
        values_courses = [0]
    else:
        labels_courses = [str(d[0]) for d in courses_data]
        values_courses = [d[1] for d in courses_data]

    # Gráfica Tiempo
    logs_today = db.query(models.ExitLog.timestamp).filter(
        cast(models.ExitLog.timestamp, Date) == target_date
    ).all()
    
    hours_map = {h: 0 for h in range(6, 19)}
    for log in logs_today:
        ts = log.timestamp
        h = ts.hour
        if h in hours_map:
            hours_map[h] += 1
            
    labels_hours = [f"{h}:00" for h in sorted(hours_map.keys())]
    values_hours = [hours_map[h] for h in sorted(hours_map.keys())]

    return {
        "courses": {"labels": labels_courses, "data": values_courses},
        "timeline": {"labels": labels_hours, "data": values_hours}
    }