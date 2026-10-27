import logging
import math

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from .. import database, deps, models
from ..schemas import LunchRequest
from ..services.lunch import get_ticket, record_lunch, reprint_ticket, search_people, ticket_payload
from ..utils.excel import build_xlsx
from ..utils.media import photo_url
from ..utils.time import day_bounds, localize

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/lunch",
    tags=["Lunch Control"],
    dependencies=[Depends(deps.require_lunch_access)],
)

templates = Jinja2Templates(directory="app/templates")

PAGE_SIZE = 50


def _person_payload(person, person_type: str) -> dict:
    scope = "students" if person_type == "student" else "employees"
    extra = person.course if person_type == "student" else (person.position or "General")
    return {
        "name": person.full_name,
        "photo": photo_url(person.photo_path, scope),
        "type": "Estudiante" if person_type == "student" else "Empleado",
        "extra": extra,
    }


def _ticket_response(outcome) -> dict:
    body = {
        "status": outcome.status,
        "message": outcome.message,
        "lunch_type": outcome.lunch_type,
        "outside_window": outcome.outside_window,
    }
    if outcome.person is not None:
        body["person"] = _person_payload(outcome.person, outcome.person_type)
    if outcome.log is not None:
        body["ticket"] = ticket_payload(outcome.log)
        body["timestamp"] = localize(outcome.log.timestamp).strftime("%Y-%m-%d %H:%M:%S")
    return body


@router.get("/scan")
def lunch_scan_view(request: Request):
    return templates.TemplateResponse(
        "lunch_scan.html", {"request": request, "user": request.state.user}
    )


@router.get("/search_person")
def search_person_for_lunch(
    q: str = Query(..., min_length=3, max_length=50),
    db: Session = Depends(database.get_db),
):
    return search_people(db, q)


@router.post("/process")
def process_lunch(
    payload: LunchRequest,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(deps.require_lunch_access),
):
    try:
        outcome = record_lunch(db, payload=payload, operator=user)
    except Exception:
        logger.exception("Error inesperado al procesar un almuerzo")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "ERROR INTERNO AL REGISTRAR EL ALMUERZO"},
        )

    return JSONResponse(status_code=outcome.http_status, content=_ticket_response(outcome))


# --- TICKETS ---


@router.get("/tickets/{public_id}")
def get_ticket_detail(
    public_id: str,
    db: Session = Depends(database.get_db),
):
    log = get_ticket(db, public_id)
    if not log:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return {"ticket": ticket_payload(log)}


@router.get("/tickets/{public_id}/print")
def print_ticket_view(
    public_id: str,
    request: Request,
    db: Session = Depends(database.get_db),
):
    log = get_ticket(db, public_id)
    if not log:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return templates.TemplateResponse(
        "lunch_ticket_print.html",
        {
            "request": request,
            "ticket": ticket_payload(log),
            "user": request.state.user,
        },
    )


@router.post("/tickets/{public_id}/reprint")
def reprint_ticket_endpoint(
    public_id: str,
    request: Request,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(deps.require_lunch_access),
):
    result = reprint_ticket(db, public_id=public_id, operator=user, request=request)
    if result is None:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    log, over_limit = result
    return {
        "status": "ok",
        "message": "Ticket listo para reimprimir",
        "ticket": ticket_payload(log),
        "printed_count": log.printed_count,
        "over_limit": over_limit,
        "print_url": f"/lunch/tickets/{public_id}/print",
    }


# --- REPORTES ---


def _report_query(db: Session, params: dict):
    start_dt, end_dt, start_date, end_date = day_bounds(
        params.get("date_start"), params.get("date_end")
    )
    query = db.query(models.LunchLog).filter(
        models.LunchLog.service_date >= start_date,
        models.LunchLog.service_date <= end_date,
    )
    lunch_type = params.get("lunch_type")
    if lunch_type and lunch_type != "Todos":
        query = query.filter(models.LunchLog.delivered_type == lunch_type)
    person_type = params.get("person_type")
    if person_type == "student":
        query = query.filter(models.LunchLog.student_id.is_not(None))
    elif person_type == "employee":
        query = query.filter(models.LunchLog.employee_id.is_not(None))
    return query, start_date, end_date


def _stats_for(query) -> dict:
    rows = (
        query.with_entities(models.LunchLog.delivered_type, func.count(models.LunchLog.id))
        .group_by(models.LunchLog.delivered_type)
        .all()
    )
    counts = dict(rows)
    return {
        "total": sum(counts.values()),
        "normal": counts.get("Normal", 0),
        "special": counts.get("Especial", 0),
    }


@router.get("/reports")
def lunch_reports_view(
    request: Request,
    date_start: str = Query(None),
    date_end: str = Query(None),
    lunch_type: str = Query(None),
    person_type: str = Query(None),
    page: int = Query(1, ge=1),
    db: Session = Depends(database.get_db),
):
    query, start_date, end_date = _report_query(
        db,
        {
            "date_start": date_start,
            "date_end": date_end,
            "lunch_type": lunch_type,
            "person_type": person_type,
        },
    )
    stats = _stats_for(query)
    total_records = stats["total"]
    total_pages = max(1, math.ceil(total_records / PAGE_SIZE))
    current_page = min(page, total_pages)

    logs = (
        query.options(
            joinedload(models.LunchLog.student),
            joinedload(models.LunchLog.employee),
            joinedload(models.LunchLog.operator),
        )
        .order_by(models.LunchLog.timestamp.desc())
        .offset((current_page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )

    return templates.TemplateResponse(
        "lunch_reports.html",
        {
            "request": request,
            "user": request.state.user,
            "logs": logs,
            "filters": {
                "date_start": start_date.isoformat(),
                "date_end": end_date.isoformat(),
                "lunch_type": lunch_type,
                "person_type": person_type,
            },
            "stats": stats,
            "pagination": {
                "page": current_page,
                "total_pages": total_pages,
                "total_records": total_records,
                "has_next": current_page < total_pages,
                "has_prev": current_page > 1,
            },
        },
    )


@router.get("/reports/export")
def export_lunch_excel(
    date_start: str = Query(...),
    date_end: str = Query(...),
    lunch_type: str = Query(None),
    person_type: str = Query(None),
    db: Session = Depends(database.get_db),
):
    query, start_date, _ = _report_query(
        db,
        {
            "date_start": date_start,
            "date_end": date_end,
            "lunch_type": lunch_type,
            "person_type": person_type,
        },
    )
    logs = (
        query.options(joinedload(models.LunchLog.operator))
        .order_by(models.LunchLog.timestamp)
        .yield_per(500)
    )

    def rows():
        for log in logs:
            if log.student_id:
                person_type_label = "Estudiante"
            elif log.employee_id:
                person_type_label = "Empleado"
            else:
                person_type_label = "?"

            yield [
                log.service_date.isoformat(),
                localize(log.timestamp).strftime("%H:%M:%S"),
                log.delivered_type,
                log.person_name or "",
                person_type_label,
                log.person_extra or "",
                log.operator.username if log.operator else "",
            ]

    return build_xlsx(
        filename=f"almuerzos_{start_date.isoformat()}.xlsx",
        sheet_name="Almuerzos",
        headers=[
            "Fecha",
            "Hora",
            "Tipo Almuerzo",
            "Nombre",
            "Tipo Persona",
            "Curso/Cargo",
            "Operador",
        ],
        rows=rows(),
    )
