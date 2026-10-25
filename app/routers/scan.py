from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import pytz
from .. import database, models, deps, auth
from ..config import settings
from ..utils.media import photo_url

router = APIRouter(
    prefix="/scan", tags=["Scanner"], dependencies=[Depends(deps.require_exit_access)]
)

templates = Jinja2Templates(directory="app/templates")
TZ_COLOMBIA = pytz.timezone(settings.timezone)
COOLDOWN_MINUTES = settings.cooldown_minutes


@router.get("/")
def scan_interface(request: Request, db: Session = Depends(database.get_db)):
    doors = db.query(models.Door).filter(models.Door.is_active.is_(True)).all()

    return templates.TemplateResponse(
        "scan.html", {"request": request, "user": request.state.user, "doors": doors}
    )


@router.post("/process")
async def process_scan(
    request: Request,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(deps.require_exit_access),
):
    data = await request.json()
    raw_qr_code = data.get("qr_code")
    door_id = data.get("door_id")

    if not raw_qr_code:
        return JSONResponse(status_code=400, content={"status": "error", "message": "QR vacío"})

    # 1. Validar Estudiante
    clean_student_id = auth.verify_qr_content(raw_qr_code)

    if not clean_student_id:
        return JSONResponse(
            content={"status": "denied", "message": "QR FALSIFICADO O INVÁLIDO", "student": None}
        )
    # 2. Buscar estudiante (Usamos el ID limpio validado)
    student = db.query(models.Student).filter(models.Student.student_id == clean_student_id).first()
    # 2. Validar Autorización
    if not student:
        return JSONResponse(
            content={"status": "error", "message": f"ID {clean_student_id} desconocido."}
        )

    if not student.is_active:
        return JSONResponse(
            content={
                "status": "denied",
                "message": "ESTUDIANTE INACTIVO",
                "student": {
                    "name": student.full_name,
                    "course": student.course,
                    "photo": photo_url(student.photo_path, "students"),
                },
            }
        )

    if not student.is_authorized:
        return JSONResponse(
            content={
                "status": "denied",
                "message": "ESTUDIANTE NO AUTORIZADO PARA SALIR",
                "student": {
                    "name": student.full_name,
                    "course": student.course,
                    "photo": photo_url(student.photo_path, "students"),
                },
            }
        )

    # 3. Validar puerta
    try:
        d_id = int(door_id)
    except (TypeError, ValueError):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "PUERTA INVÁLIDA", "student": None},
        )

    door = (
        db.query(models.Door)
        .filter(models.Door.id == d_id, models.Door.is_active.is_(True))
        .first()
    )
    if not door:
        return JSONResponse(
            status_code=403,
            content={"status": "denied", "message": "PUERTA INVÁLIDA O INACTIVA", "student": None},
        )

    # 4. VALIDACIÓN DE TIEMPO (COOLDOWN)
    now_co = datetime.now(TZ_COLOMBIA)

    # Buscar la última salida registrada de este estudiante
    last_log = (
        db.query(models.ExitLog)
        .filter(models.ExitLog.student_id == student.id)
        .order_by(models.ExitLog.timestamp.desc())
        .first()
    )

    if last_log:
        last_time = last_log.timestamp

        # Normalizar zonas horarias (por si la BD devuelve naive datetime)
        if last_time.tzinfo is None:
            last_time = TZ_COLOMBIA.localize(last_time)

        time_diff = now_co - last_time

        if time_diff < timedelta(minutes=COOLDOWN_MINUTES):
            minutes_ago = int(time_diff.total_seconds() / 60)
            return JSONResponse(
                content={
                    "status": "warning",  # Nuevo estado: Advertencia
                    "message": f"YA SALIÓ HACE {minutes_ago} MINUTOS",
                    "student": {
                        "name": student.full_name,
                        "course": student.course,
                        "photo": photo_url(student.photo_path, "students"),
                    },
                }
            )

    # 5. Registrar Salida (Si pasó todas las validaciones)
    new_log = models.ExitLog(
        student_id=student.id,
        operator_id=user.id,
        door_id=door.id,
        timestamp=now_co,
        student_name=student.full_name,
        course=student.course,
        door_name=door.name,
        authorized_at_scan=student.is_authorized,
    )
    db.add(new_log)
    db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": "SALIDA REGISTRADA",
            "timestamp": now_co.strftime("%H:%M:%S"),
            "student": {
                "name": student.full_name,
                "course": student.course,
                "photo": photo_url(student.photo_path, "students"),
            },
        }
    )
