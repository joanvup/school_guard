import logging
from dataclasses import dataclass
from datetime import timedelta

from .. import models
from ..config import settings
from ..utils.time import localize, now_local
from .audit import add_scan_attempt, record_scan_attempt
from .qr import verify_qr

logger = logging.getLogger(__name__)


@dataclass
class ExitOutcome:
    status: str
    http_status: int
    message: str
    student: models.Student | None = None
    timestamp: str | None = None
    previous_timestamp: str | None = None


def _log_attempt(
    db,
    *,
    result: str,
    operator_id: int,
    student_id: int | None = None,
    door_id: int | None = None,
    code: str | None = None,
    reason: str | None = None,
) -> None:
    record_scan_attempt(
        db,
        module="exit",
        method="qr",
        result=result,
        student_id=student_id,
        operator_id=operator_id,
        door_id=door_id,
        code=code,
        reason=reason,
    )


def record_exit(
    db,
    *,
    qr_code: str,
    door_id: int,
    operator: models.User,
) -> ExitOutcome:
    payload = verify_qr(qr_code)
    if payload is None:
        _log_attempt(
            db,
            result="invalid_signature",
            operator_id=operator.id,
            code=qr_code,
            reason="QR inválido o firma alterada",
        )
        return ExitOutcome("denied", 403, "QR FALSIFICADO O INVÁLIDO")

    if payload.person_type == "employee":
        _log_attempt(
            db,
            result="denied",
            operator_id=operator.id,
            code=qr_code,
            reason="Los carnets de empleado no registran salidas peatonales",
        )
        return ExitOutcome("denied", 403, "CARNET DE EMPLEADO NO VÁLIDO PARA SALIDA")

    student = (
        db.query(models.Student)
        .filter(models.Student.student_id == payload.identifier)
        .with_for_update()
        .first()
    )
    if not student:
        _log_attempt(
            db,
            result="unknown_person",
            operator_id=operator.id,
            code=qr_code,
            reason=f"ID {payload.identifier} desconocido",
        )
        return ExitOutcome("denied", 403, f"ID {payload.identifier} DESCONOCIDO")

    if not student.is_active:
        _log_attempt(
            db,
            result="denied",
            operator_id=operator.id,
            student_id=student.id,
            code=qr_code,
            reason="Estudiante inactivo",
        )
        return ExitOutcome("denied", 403, "ESTUDIANTE INACTIVO", student=student)

    if not student.is_authorized:
        _log_attempt(
            db,
            result="denied",
            operator_id=operator.id,
            student_id=student.id,
            code=qr_code,
            reason="Estudiante no autorizado para salir",
        )
        return ExitOutcome(
            "denied",
            403,
            "ESTUDIANTE NO AUTORIZADO PARA SALIR",
            student=student,
        )

    door = (
        db.query(models.Door)
        .filter(models.Door.id == door_id, models.Door.is_active.is_(True))
        .first()
    )
    if not door:
        _log_attempt(
            db,
            result="denied",
            operator_id=operator.id,
            student_id=student.id,
            code=qr_code,
            reason=f"Puerta {door_id} inválida o inactiva",
        )
        return ExitOutcome("denied", 403, "PUERTA INVÁLIDA O INACTIVA", student=student)

    now = now_local()

    if settings.cooldown_minutes:
        last_log = (
            db.query(models.ExitLog)
            .filter(models.ExitLog.student_id == student.id)
            .order_by(models.ExitLog.timestamp.desc())
            .with_for_update()
            .first()
        )
        if last_log:
            last_time = localize(last_log.timestamp)
            time_diff = now - last_time
            if time_diff < timedelta(minutes=settings.cooldown_minutes):
                minutes_ago = int(time_diff.total_seconds() // 60)
                detail = (
                    "hace menos de 1 minuto" if minutes_ago < 1 else f"hace {minutes_ago} minutos"
                )
                _log_attempt(
                    db,
                    result="duplicate",
                    operator_id=operator.id,
                    student_id=student.id,
                    door_id=door.id,
                    code=qr_code,
                    reason=f"Salida duplicada: ya salió {detail}",
                )
                return ExitOutcome(
                    "warning",
                    409,
                    f"YA SALIÓ {detail.upper()}",
                    student=student,
                    previous_timestamp=last_time.strftime("%H:%M:%S"),
                )

    new_log = models.ExitLog(
        student_id=student.id,
        operator_id=operator.id,
        door_id=door.id,
        timestamp=now,
        student_name=student.full_name,
        course=student.course,
        door_name=door.name,
        authorized_at_scan=student.is_authorized,
    )
    db.add(new_log)
    add_scan_attempt(
        db,
        module="exit",
        method="qr",
        result="success",
        student_id=student.id,
        operator_id=operator.id,
        door_id=door.id,
        code=qr_code,
    )

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("No se pudo registrar la salida del estudiante %s", student.id)
        _log_attempt(
            db,
            result="error",
            operator_id=operator.id,
            student_id=student.id,
            door_id=door.id,
            code=qr_code,
            reason="Error al registrar la salida",
        )
        raise

    return ExitOutcome(
        "success",
        200,
        "SALIDA REGISTRADA",
        student=student,
        timestamp=now.strftime("%H:%M:%S"),
    )
