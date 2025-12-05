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

def get_date_obj(date_str: str = None):
    if date_str:
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    return datetime.now(TZ_COLOMBIA).date()

# --- VISTA HTML PRINCIPAL (Routing por Rol) ---
@router.get("/dashboard")
def dashboard_view(request: Request, db: Session = Depends(database.get_db)):
    user = request.state.user
    today_str = datetime.now(TZ_COLOMBIA).strftime('%Y-%m-%d')
    
    # LOGICA DE REDIRECCIÓN POR ROL
    if user.role == models.UserRole.LUNCH_OP:
        # El operador de almuerzo ve su propio dashboard
        return templates.TemplateResponse("dashboard_lunch.html", {
            "request": request, "user": user, "today_date": today_str
        })
    else:
        # Admin y Operador de Puerta ven el dashboard de Salidas
        return templates.TemplateResponse("dashboard.html", {
            "request": request, "user": user, "today_date": today_str
        })

# ==========================================
# APIs PARA DASHBOARD DE SALIDAS (PORTERÍA)
# ==========================================

@router.get("/api/dashboard/stats")
def get_exit_stats(date: str = Query(None), db: Session = Depends(database.get_db)):
    target_date = get_date_obj(date)
    
    exits_count = db.query(models.ExitLog).filter(cast(models.ExitLog.timestamp, Date) == target_date).count()
    total_students = db.query(models.Student).count()
    
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
        if exits_count > 0: percent = round((count / exits_count) * 100, 1)
        doors_stats.append({"id": door.id, "name": door.name, "count": count, "percent": percent})
    
    doors_stats.sort(key=lambda x: x['count'], reverse=True)
    return {"exits_count": exits_count, "total_students": total_students, "doors_data": doors_stats}

@router.get("/api/dashboard/chart-data")
def get_exit_charts(date: str = Query(None), db: Session = Depends(database.get_db)):
    target_date = get_date_obj(date)
    # Gráfica Cursos
    courses_data = db.query(models.Student.course, func.count(models.ExitLog.id))\
        .join(models.ExitLog).filter(cast(models.ExitLog.timestamp, Date) == target_date)\
        .group_by(models.Student.course).all()
    
    labels_c = [str(d[0]) for d in courses_data] if courses_data else ["Sin datos"]
    values_c = [d[1] for d in courses_data] if courses_data else [0]

    # Gráfica Tiempo
    logs = db.query(models.ExitLog.timestamp).filter(cast(models.ExitLog.timestamp, Date) == target_date).all()
    hours_map = {h: 0 for h in range(6, 19)}
    for l in logs:
        if l.timestamp.hour in hours_map: hours_map[l.timestamp.hour] += 1
            
    return {
        "courses": {"labels": labels_c, "data": values_c},
        "timeline": {"labels": [f"{h}:00" for h in sorted(hours_map)], "data": [hours_map[h] for h in sorted(hours_map)]}
    }

@router.get("/api/dashboard/details")
def get_exit_details(type: str = Query(...), id: int = Query(None), date: str = Query(None), db: Session = Depends(database.get_db)):
    target_date = get_date_obj(date)
    q = db.query(models.ExitLog).filter(cast(models.ExitLog.timestamp, Date) == target_date)
    if type == 'door' and id: q = q.filter(models.ExitLog.door_id == id)
    
    logs = q.order_by(models.ExitLog.timestamp.desc()).all()
    return [{
        "photo": l.student.photo_path, "name": l.student.full_name,
        "course": l.student.course, "time": l.timestamp.strftime("%I:%M:%S %p"),
        "door": l.door.name
    } for l in logs]


# ==========================================
# APIs PARA DASHBOARD DE ALMUERZOS (COMEDOR)
# ==========================================

@router.get("/api/dashboard/lunch/stats")
def get_lunch_stats(date: str = Query(None), db: Session = Depends(database.get_db)):
    target_date = get_date_obj(date)
    
    # Query base filtrado por fecha
    base_q = db.query(models.LunchLog).filter(cast(models.LunchLog.timestamp, Date) == target_date)
    
    total = base_q.count()
    normal = base_q.filter(models.LunchLog.delivered_type == "Normal").count()
    special = base_q.filter(models.LunchLog.delivered_type == "Especial").count()
    
    # Estudiantes vs Empleados
    students_count = base_q.filter(models.LunchLog.student_id != None).count()
    employees_count = base_q.filter(models.LunchLog.employee_id != None).count()

    return {
        "total": total,
        "normal": normal,
        "special": special,
        "by_person": {"students": students_count, "employees": employees_count}
    }

@router.get("/api/dashboard/lunch/chart-data")
def get_lunch_charts(date: str = Query(None), db: Session = Depends(database.get_db)):
    target_date = get_date_obj(date)
    
    # 1. Timeline (Por hora)
    logs = db.query(models.LunchLog.timestamp).filter(cast(models.LunchLog.timestamp, Date) == target_date).all()
    hours_map = {h: 0 for h in range(11, 15)} # Almuerzos suelen ser 11am - 2pm (ajustable)
    
    for l in logs:
        h = l.timestamp.hour
        if h in hours_map: hours_map[h] += 1
        elif h < 11 and 11 in hours_map: hours_map[11] += 1 # Agrupar tempraneros
        elif h > 14 and 14 in hours_map: hours_map[14] += 1 # Agrupar tardíos
            
    # 2. Distribución (Normal vs Especial)
    # Ya lo tenemos en stats, pero lo reenviamos para la gráfica
    n_count = db.query(models.LunchLog).filter(cast(models.LunchLog.timestamp, Date) == target_date, models.LunchLog.delivered_type == "Normal").count()
    s_count = db.query(models.LunchLog).filter(cast(models.LunchLog.timestamp, Date) == target_date, models.LunchLog.delivered_type == "Especial").count()

    return {
        "timeline": {"labels": [f"{h}:00" for h in sorted(hours_map)], "data": [hours_map[h] for h in sorted(hours_map)]},
        "distribution": {"labels": ["Normal", "Especial"], "data": [n_count, s_count]}
    }

@router.get("/api/dashboard/lunch/details")
def get_lunch_details(type: str = Query(...), date: str = Query(None), db: Session = Depends(database.get_db)):
    target_date = get_date_obj(date)
    q = db.query(models.LunchLog).filter(cast(models.LunchLog.timestamp, Date) == target_date)
    
    if type == 'Normal': q = q.filter(models.LunchLog.delivered_type == 'Normal')
    elif type == 'Especial': q = q.filter(models.LunchLog.delivered_type == 'Especial')
    
    logs = q.order_by(models.LunchLog.timestamp.desc()).all()
    
    data = []
    for l in logs:
        if l.student:
            name = l.student.full_name
            photo = l.student.photo_path
            extra = l.student.course
        elif l.employee:
            name = l.employee.full_name
            photo = l.employee.photo_path
            extra = l.employee.position
        else:
            name = "?"
            photo = None
            extra = ""
            
        data.append({
            "photo": photo, "name": name, "extra": extra,
            "time": l.timestamp.strftime("%I:%M:%S %p"),
            "type": l.delivered_type
        })
    return data