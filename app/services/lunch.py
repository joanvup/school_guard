import logging
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..schemas import LunchRequest
from ..utils.media import photo_url
from ..utils.time import localize, now_local
from .audit import add_audit, add_scan_attempt, record_scan_attempt
from .qr import verify_qr

logger = logging.getLogger(__name__)

VALID_LUNCH_TYPES = ("Normal", "Especial")


@dataclass
class LunchOutcome:
    status: str
    http_status: int
    message: str
    person: models.Student | models.Employee | None = None
    person_type: str | None = None
    lunch_type: str | None = None
    log: models.LunchLog | None = None
    outside_window: bool = False


def _display_type(person_type: str) -> str:
    return "Estudiante" if person_type == "student" else "Empleado"


def _extra(person, person_type: str) -> str:
    if person_type == "student":
        return person.course or ""
    return person.position or ""


def _find_person(
    db: Session, payload: LunchRequest
) -> tuple[object | None, str | None, str | None]:
    """Retorna (persona, tipo, error). error='invalid_signature' si el QR no es válido."""
    if payload.method == "qr":
        qr = verify_qr(payload.code)
        if qr is None:
            return None, None, "invalid_signature"

        if qr.person_type == "student":
            person = (
                db.query(models.Student).filter(models.Student.student_id == qr.identifier).first()
            )
            return person, "student", None
        if qr.person_type == "employee":
            person = (
                db.query(models.Employee).filter(models.Employee.doc_id == qr.identifier).first()
            )
            return person, "employee", None

        # v1 no incluye tipo: se conserva la compatibilidad con carnets impresos.
        person = db.query(models.Student).filter(models.Student.student_id == qr.identifier).first()
        if person:
            return person, "student", None
        person = db.query(models.Employee).filter(models.Employee.doc_id == qr.identifier).first()
        return person, "employee" if person else None, None

    if payload.method == "rfid":
        person = db.query(models.Student).filter(models.Student.rfid_code == payload.code).first()
        if person:
            return person, "student", None
        person = db.query(models.Employee).filter(models.Employee.rfid_code == payload.code).first()
        return person, "employee" if person else None, None

    if payload.person_type == "student":
        person = db.query(models.Student).filter(models.Student.id == payload.person_id).first()
    else:
        person = db.query(models.Employee).filter(models.Employee.id == payload.person_id).first()
    return person, payload.person_type, None


def _deny(
    db: Session,
    *,
    payload: LunchRequest,
    operator: models.User,
    result: str,
    reason: str,
    message: str,
    person=None,
    person_type: str | None = None,
    http_status: int = 403,
) -> LunchOutcome:
    record_scan_attempt(
        db,
        module="lunch",
        method=payload.method,
        result=result,
        student_id=person.id if person is not None and person_type == "student" else None,
        employee_id=person.id if person is not None and person_type == "employee" else None,
        operator_id=operator.id,
        code=payload.code,
        reason=reason,
    )
    return LunchOutcome(
        "denied",
        http_status,
        message,
        person=person,
        person_type=person_type,
    )


def ticket_payload(log: models.LunchLog) -> dict:
    person_type = "student" if log.student_id else "employee"
    return {
        "public_id": log.public_id,
        "number": f"{log.service_date.strftime('%Y%m%d')}-{log.id:05d}",
        "name": log.person_name or "Sin nombre",
        "lunch_type": log.delivered_type,
        "extra": log.person_extra or "",
        "person_type": _display_type(person_type),
        "date": log.service_date.isoformat(),
        "time": localize(log.timestamp).strftime("%I:%M %p"),
        "qr": log.public_id,
    }


def _out_of_window(now) -> bool:
    start, end = settings.lunch_window_times
    return not (start <= now.time() <= end)


def record_lunch(
    db: Session,
    *,
    payload: LunchRequest,
    operator: models.User,
) -> LunchOutcome:
    person, person_type, error = _find_person(db, payload)

    if error == "invalid_signature":
        return _deny(
            db,
            payload=payload,
            operator=operator,
            result="invalid_signature",
            reason="QR inválido o firma alterada",
            message="QR FALSIFICADO O INVÁLIDO",
        )

    if not person:
        return _deny(
            db,
            payload=payload,
            operator=operator,
            result="unknown_person",
            reason="Persona no registrada",
            message="NO ENCONTRADO O NO REGISTRADO",
        )

    if not person.is_active:
        return _deny(
            db,
            payload=payload,
            operator=operator,
            result="denied",
            reason="Persona inactiva",
            message="PERSONA INACTIVA",
            person=person,
            person_type=person_type,
        )

    if not person.has_lunch:
        return _deny(
            db,
            payload=payload,
            operator=operator,
            result="denied",
            reason="Sin almuerzo asignado",
            message="NO TIENE ALMUERZO ASIGNADO",
            person=person,
            person_type=person_type,
        )

    lunch_type = person.lunch_type or "Normal"
    if lunch_type not in VALID_LUNCH_TYPES:
        return _deny(
            db,
            payload=payload,
            operator=operator,
            result="denied",
            reason=f"Tipo de almuerzo inválido: {lunch_type}",
            message="PLAN DE ALMUERZO INVÁLIDO",
            person=person,
            person_type=person_type,
        )

    now = now_local()
    outside_window = _out_of_window(now)
    if outside_window and settings.lunch_window_enforcement == "deny":
        return _deny(
            db,
            payload=payload,
            operator=operator,
            result="denied",
            reason="Entrega fuera de la ventana horaria",
            message="FUERA DE LA VENTANA DE ALMUERZO",
            person=person,
            person_type=person_type,
        )

    extra = _extra(person, person_type)
    new_log = models.LunchLog(
        student_id=person.id if person_type == "student" else None,
        employee_id=person.id if person_type == "employee" else None,
        operator_id=operator.id,
        timestamp=now,
        service_date=now.date(),
        delivered_type=lunch_type,
        identification_method=payload.method,
        person_name=person.full_name,
        person_extra=extra,
    )
    db.add(new_log)
    add_scan_attempt(
        db,
        module="lunch",
        method=payload.method,
        result="success",
        student_id=person.id if person_type == "student" else None,
        employee_id=person.id if person_type == "employee" else None,
        operator_id=operator.id,
        code=payload.code,
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate_filters = [models.LunchLog.service_date == now.date()]
        if person_type == "student":
            duplicate_filters.append(models.LunchLog.student_id == person.id)
        else:
            duplicate_filters.append(models.LunchLog.employee_id == person.id)
        existing = db.query(models.LunchLog).filter(*duplicate_filters).first()
        record_scan_attempt(
            db,
            module="lunch",
            method=payload.method,
            result="duplicate",
            student_id=person.id if person_type == "student" else None,
            employee_id=person.id if person_type == "employee" else None,
            operator_id=operator.id,
            code=payload.code,
            reason="Almuerzo ya reclamado hoy",
        )
        if existing:
            return LunchOutcome(
                "warning",
                409,
                f"YA RECLAMÓ ALMUERZO A LAS {localize(existing.timestamp).strftime('%I:%M %p')}",
                person=person,
                person_type=person_type,
                lunch_type=existing.delivered_type,
                log=existing,
            )
        raise
    except Exception:
        db.rollback()
        logger.exception("No se pudo registrar el almuerzo")
        record_scan_attempt(
            db,
            module="lunch",
            method=payload.method,
            result="error",
            student_id=person.id if person_type == "student" else None,
            employee_id=person.id if person_type == "employee" else None,
            operator_id=operator.id,
            code=payload.code,
            reason="Error al registrar el almuerzo",
        )
        raise

    db.refresh(new_log)
    message = "ALMUERZO AUTORIZADO"
    if outside_window and settings.lunch_window_enforcement == "warn":
        message += " (FUERA DE VENTANA)"
    return LunchOutcome(
        "success",
        200,
        message,
        person=person,
        person_type=person_type,
        lunch_type=lunch_type,
        log=new_log,
        outside_window=outside_window,
    )


def get_ticket(db: Session, public_id: str) -> models.LunchLog | None:
    return db.query(models.LunchLog).filter(models.LunchLog.public_id == public_id).first()


def reprint_ticket(
    db: Session,
    *,
    public_id: str,
    operator: models.User,
    request: Request | None = None,
) -> tuple[models.LunchLog, bool] | None:
    log = get_ticket(db, public_id)
    if not log:
        return None

    new_count = (log.printed_count or 0) + 1
    db.query(models.LunchLog).filter(models.LunchLog.id == log.id).update(
        {
            models.LunchLog.printed_count: models.LunchLog.printed_count + 1,
            models.LunchLog.last_printed_at: now_local(),
        },
        synchronize_session=False,
    )
    add_audit(
        db,
        action="lunch.ticket_reprinted",
        actor_id=operator.id,
        entity_type="lunch_log",
        entity_id=log.id,
        details={"public_id": public_id, "printed_count": new_count},
        request=request,
    )
    db.commit()
    db.refresh(log)
    return log, new_count > 3


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_people(db: Session, query_text: str) -> list[dict]:
    term = query_text.strip()[:50]
    if len(term) < 3:
        return []

    pattern = f"%{_escape_like(term)}%"
    students = (
        db.query(models.Student)
        .filter(
            models.Student.is_active.is_(True),
            models.Student.full_name.ilike(pattern, escape="\\"),
        )
        .order_by(models.Student.full_name)
        .limit(5)
        .all()
    )
    employees = (
        db.query(models.Employee)
        .filter(
            models.Employee.is_active.is_(True),
            models.Employee.full_name.ilike(pattern, escape="\\"),
        )
        .order_by(models.Employee.full_name)
        .limit(5)
        .all()
    )

    results = []
    for student in students:
        results.append(
            {
                "person_id": student.id,
                "person_type": "student",
                "type": "Estudiante",
                "name": student.full_name,
                "extra": student.course,
                "photo": photo_url(student.photo_path, "students"),
                "has_lunch": bool(student.has_lunch),
            }
        )
    for employee in employees:
        results.append(
            {
                "person_id": employee.id,
                "person_type": "employee",
                "type": "Empleado",
                "name": employee.full_name,
                "extra": employee.position or "General",
                "photo": photo_url(employee.photo_path, "employees"),
                "has_lunch": bool(employee.has_lunch),
            }
        )

    results.sort(key=lambda item: item["name"].casefold())
    return results
