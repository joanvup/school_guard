from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
import pandas as pd
import io
from .. import database, models, deps
from ..utils.time import day_bounds

router = APIRouter(
    prefix="/reports", tags=["Reports"], dependencies=[Depends(deps.require_exit_access)]
)

templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def view_reports(
    request: Request,
    date_start: str = Query(None),
    date_end: str = Query(None),
    # CAMBIO: Recibir como str para manejar la cadena vacía "" sin error
    door_id: str = Query(None),
    db: Session = Depends(database.get_db),
):
    start_dt, end_dt, start_date, end_date = day_bounds(date_start, date_end)

    query = db.query(models.ExitLog).filter(
        models.ExitLog.timestamp >= start_dt, models.ExitLog.timestamp <= end_dt
    )

    # CAMBIO: Validar si door_id es un número antes de filtrar
    selected_door_id = None
    if door_id and door_id.strip().isdigit():
        selected_door_id = int(door_id)
        query = query.filter(models.ExitLog.door_id == selected_door_id)

    logs = query.order_by(desc(models.ExitLog.timestamp)).all()
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
                "door_id": selected_door_id,  # Pasamos el int limpio al template
            },
            "user": request.state.user,
        },
    )


@router.get("/export")
def export_reports(
    date_start: str = Query(...),
    date_end: str = Query(...),
    # CAMBIO: Recibir como str también aquí
    door_id: str = Query(None),
    db: Session = Depends(database.get_db),
):
    start_dt, end_dt, start_date, end_date = day_bounds(date_start, date_end)

    query = (
        db.query(models.ExitLog)
        .join(models.Student)
        .join(models.Door)
        .join(models.User)
        .filter(models.ExitLog.timestamp >= start_dt, models.ExitLog.timestamp <= end_dt)
    )

    # CAMBIO: Validar filtro
    if door_id and door_id.strip().isdigit():
        query = query.filter(models.ExitLog.door_id == int(door_id))

    logs = query.order_by(models.ExitLog.timestamp).all()

    # Crear DataFrame
    data = []
    for log in logs:
        data.append(
            {
                "Fecha y Hora": log.timestamp.strftime("%Y-%m-%d %I:%M:%S %p"),  # Formato AM/PM
                "ID Estudiante": log.student.student_id,
                "Nombre Estudiante": log.student.full_name,
                "Curso": log.student.course,
                "Puerta": log.door.name,
                "Operador": log.operator.username,
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
