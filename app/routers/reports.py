import io
import math

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from .. import database, deps, models
from ..utils.time import day_bounds

router = APIRouter(
    prefix="/reports", tags=["Reports"], dependencies=[Depends(deps.require_exit_access)]
)

templates = Jinja2Templates(directory="app/templates")

PAGE_SIZE = 50
FORMULA_PREFIXES = ("=", "+", "-", "@")


def _selected_door_id(door_id: str | None) -> int | None:
    if door_id is None or not door_id.strip():
        return None
    if not door_id.strip().isdigit():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Puerta inválida",
        )
    return int(door_id.strip())


def _safe_cell(value):
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _sorted_logs_query(db: Session, start_dt, end_dt, door_id: int | None):
    query = db.query(models.ExitLog).filter(
        models.ExitLog.timestamp >= start_dt, models.ExitLog.timestamp <= end_dt
    )
    if door_id is not None:
        query = query.filter(models.ExitLog.door_id == door_id)
    return query


@router.get("/")
def view_reports(
    request: Request,
    date_start: str = Query(None),
    date_end: str = Query(None),
    door_id: str = Query(None),
    page: int = Query(1, ge=1),
    db: Session = Depends(database.get_db),
):
    start_dt, end_dt, start_date, end_date = day_bounds(date_start, date_end)
    selected_door_id = _selected_door_id(door_id)

    query = _sorted_logs_query(db, start_dt, end_dt, selected_door_id)
    total_records = query.count()
    total_pages = max(1, math.ceil(total_records / PAGE_SIZE))
    current_page = min(page, total_pages)

    logs = (
        query.options(
            joinedload(models.ExitLog.student),
            joinedload(models.ExitLog.operator),
        )
        .order_by(desc(models.ExitLog.timestamp))
        .offset((current_page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )
    doors = db.query(models.Door).all()

    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            "logs": logs,
            "doors": doors,
            "filters": {
                "date_start": start_date.isoformat(),
                "date_end": end_date.isoformat(),
                "door_id": selected_door_id,
            },
            "pagination": {
                "page": current_page,
                "total_pages": total_pages,
                "total_records": total_records,
                "has_next": current_page < total_pages,
                "has_prev": current_page > 1,
            },
            "user": request.state.user,
        },
    )


@router.get("/export")
def export_reports(
    date_start: str = Query(...),
    date_end: str = Query(...),
    door_id: str = Query(None),
    db: Session = Depends(database.get_db),
):
    start_dt, end_dt, start_date, end_date = day_bounds(date_start, date_end)
    selected_door_id = _selected_door_id(door_id)

    logs = (
        _sorted_logs_query(db, start_dt, end_dt, selected_door_id)
        .options(joinedload(models.ExitLog.student), joinedload(models.ExitLog.operator))
        .order_by(models.ExitLog.timestamp)
        .all()
    )

    data = []
    for log in logs:
        student_id = log.student.student_id if log.student else ""
        data.append(
            {
                "Fecha y Hora": log.timestamp.strftime("%Y-%m-%d %I:%M:%S %p"),
                "ID Estudiante": _safe_cell(student_id),
                "Nombre Estudiante": _safe_cell(log.student_name or ""),
                "Curso": _safe_cell(log.course or ""),
                "Puerta": _safe_cell(log.door_name or ""),
                "Operador": _safe_cell(log.operator.username if log.operator else ""),
            }
        )

    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Reporte Salidas")
    output.seek(0)

    headers = {
        "Content-Disposition": f'attachment; filename="reporte_{date_start}_{date_end}.xlsx"'
    }
    return Response(
        content=output.getvalue(),
        headers=headers,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
