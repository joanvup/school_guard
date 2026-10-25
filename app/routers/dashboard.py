from collections import defaultdict

from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from .. import database, deps, models
from ..utils.media import photo_url
from ..utils.time import day_range, parse_date, today_local

router = APIRouter(dependencies=[Depends(deps.require_user)])
templates = Jinja2Templates(directory="app/templates")


def _exit_range(target_date):
    start_dt, end_dt = day_range(target_date)
    return models.ExitLog.timestamp >= start_dt, models.ExitLog.timestamp <= end_dt


# --- VISTA HTML PRINCIPAL (Routing por Rol) ---
@router.get("/dashboard")
def dashboard_view(request: Request, db: Session = Depends(database.get_db)):
    user = request.state.user
    today_str = today_local().isoformat()

    if user.role == models.UserRole.LUNCH_OP:
        return templates.TemplateResponse(
            "dashboard_lunch.html", {"request": request, "user": user, "today_date": today_str}
        )
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "user": user, "today_date": today_str}
    )


# ==========================================
# APIs PARA DASHBOARD DE SALIDAS (PORTERÍA)
# ==========================================


@router.get(
    "/api/dashboard/stats",
    dependencies=[Depends(deps.require_exit_access)],
)
def get_exit_stats(date: str = Query(None), db: Session = Depends(database.get_db)):
    target_date = parse_date(date)
    start_filter, end_filter = _exit_range(target_date)

    exits_count = db.query(models.ExitLog).filter(start_filter, end_filter).count()
    total_students = db.query(models.Student).filter(models.Student.is_active.is_(True)).count()

    door_counts = (
        db.query(models.Door.id, models.Door.name, func.count(models.ExitLog.id))
        .outerjoin(
            models.ExitLog,
            (models.ExitLog.door_id == models.Door.id) & start_filter & end_filter,
        )
        .filter(models.Door.is_active.is_(True))
        .group_by(models.Door.id, models.Door.name)
        .all()
    )

    doors_stats = []
    for door_id, door_name, count in door_counts:
        percent = round((count / exits_count) * 100, 1) if exits_count else 0
        doors_stats.append({"id": door_id, "name": door_name, "count": count, "percent": percent})
    doors_stats.sort(key=lambda item: item["count"], reverse=True)

    return {
        "exits_count": exits_count,
        "total_students": total_students,
        "doors_data": doors_stats,
    }


@router.get(
    "/api/dashboard/chart-data",
    dependencies=[Depends(deps.require_exit_access)],
)
def get_exit_charts(date: str = Query(None), db: Session = Depends(database.get_db)):
    target_date = parse_date(date)
    start_filter, end_filter = _exit_range(target_date)

    courses_data = (
        db.query(models.ExitLog.course, func.count(models.ExitLog.id))
        .filter(start_filter, end_filter)
        .group_by(models.ExitLog.course)
        .all()
    )

    timeline = defaultdict(int)
    timestamps = db.query(models.ExitLog.timestamp).filter(start_filter, end_filter).all()
    for (timestamp,) in timestamps:
        timeline[timestamp.hour] += 1

    hours = sorted(timeline)
    return {
        "courses": {
            "labels": [str(course or "Sin curso") for course, _ in courses_data] or ["Sin datos"],
            "data": [count for _, count in courses_data] or [0],
        },
        "timeline": {
            "labels": [f"{hour}:00" for hour in hours] or ["Sin datos"],
            "data": [timeline[hour] for hour in hours] or [0],
        },
    }


@router.get(
    "/api/dashboard/details",
    dependencies=[Depends(deps.require_exit_access)],
)
def get_exit_details(
    type: str = Query(...),
    id: int = Query(None),
    date: str = Query(None),
    db: Session = Depends(database.get_db),
):
    target_date = parse_date(date)
    start_filter, end_filter = _exit_range(target_date)

    query = (
        db.query(models.ExitLog)
        .filter(start_filter, end_filter)
        .options(joinedload(models.ExitLog.student))
    )
    if type == "door" and id:
        query = query.filter(models.ExitLog.door_id == id)

    logs = query.order_by(models.ExitLog.timestamp.desc()).all()
    return [
        {
            "photo": photo_url(log.student.photo_path, "students") if log.student else None,
            "name": log.student_name or (log.student.full_name if log.student else "Desconocido"),
            "course": log.course or (log.student.course if log.student else ""),
            "time": log.timestamp.strftime("%I:%M:%S %p"),
            "door": log.door_name or "",
        }
        for log in logs
    ]


# ==========================================
# APIs PARA DASHBOARD DE ALMUERZOS (COMEDOR)
# ==========================================


@router.get(
    "/api/dashboard/lunch/stats",
    dependencies=[Depends(deps.require_lunch_access)],
)
def get_lunch_stats(date: str = Query(None), db: Session = Depends(database.get_db)):
    target_date = parse_date(date)

    rows = (
        db.query(models.LunchLog.delivered_type, func.count(models.LunchLog.id))
        .filter(models.LunchLog.service_date == target_date)
        .group_by(models.LunchLog.delivered_type)
        .all()
    )
    type_counts = dict(rows)

    students_count = (
        db.query(models.LunchLog)
        .filter(
            models.LunchLog.service_date == target_date,
            models.LunchLog.student_id.is_not(None),
        )
        .count()
    )
    employees_count = (
        db.query(models.LunchLog)
        .filter(
            models.LunchLog.service_date == target_date,
            models.LunchLog.employee_id.is_not(None),
        )
        .count()
    )

    return {
        "total": sum(type_counts.values()),
        "normal": type_counts.get("Normal", 0),
        "special": type_counts.get("Especial", 0),
        "by_person": {"students": students_count, "employees": employees_count},
    }


@router.get(
    "/api/dashboard/lunch/chart-data",
    dependencies=[Depends(deps.require_lunch_access)],
)
def get_lunch_charts(date: str = Query(None), db: Session = Depends(database.get_db)):
    target_date = parse_date(date)

    rows = (
        db.query(models.LunchLog.timestamp)
        .filter(models.LunchLog.service_date == target_date)
        .all()
    )
    timeline = defaultdict(int)
    for (timestamp,) in rows:
        timeline[timestamp.hour] += 1

    hours = sorted(timeline)
    distribution = (
        db.query(models.LunchLog.delivered_type, func.count(models.LunchLog.id))
        .filter(models.LunchLog.service_date == target_date)
        .group_by(models.LunchLog.delivered_type)
        .all()
    )
    dist_map = dict(distribution)

    return {
        "timeline": {
            "labels": [f"{hour}:00" for hour in hours] or ["Sin datos"],
            "data": [timeline[hour] for hour in hours] or [0],
        },
        "distribution": {
            "labels": ["Normal", "Especial"],
            "data": [dist_map.get("Normal", 0), dist_map.get("Especial", 0)],
        },
    }


@router.get(
    "/api/dashboard/lunch/details",
    dependencies=[Depends(deps.require_lunch_access)],
)
def get_lunch_details(
    type: str = Query(...), date: str = Query(None), db: Session = Depends(database.get_db)
):
    target_date = parse_date(date)

    query = (
        db.query(models.LunchLog)
        .filter(models.LunchLog.service_date == target_date)
        .options(
            joinedload(models.LunchLog.student),
            joinedload(models.LunchLog.employee),
        )
    )
    if type == "Normal":
        query = query.filter(models.LunchLog.delivered_type == "Normal")
    elif type == "Especial":
        query = query.filter(models.LunchLog.delivered_type == "Especial")

    logs = query.order_by(models.LunchLog.timestamp.desc()).all()

    data = []
    for log in logs:
        if log.student_id:
            person = log.student
            photo = photo_url(person.photo_path, "students") if person else None
            extra = log.person_extra or (person.course if person else "")
        else:
            person = log.employee
            photo = photo_url(person.photo_path, "employees") if person else None
            extra = log.person_extra or (person.position if person else "")

        data.append(
            {
                "photo": photo,
                "name": log.person_name or (person.full_name if person else "?"),
                "extra": extra,
                "time": log.timestamp.strftime("%I:%M:%S %p"),
                "type": log.delivered_type,
                "public_id": log.public_id,
            }
        )
    return data
