import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import database, deps, models
from ..schemas import ScanRequest, ScanResponse, StudentInfo
from ..services.exits import record_exit
from ..utils.media import photo_url

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/scan", tags=["Scanner"], dependencies=[Depends(deps.require_exit_access)]
)

templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def scan_interface(request: Request, db: Session = Depends(database.get_db)):
    doors = db.query(models.Door).filter(models.Door.is_active.is_(True)).all()

    return templates.TemplateResponse(
        "scan.html", {"request": request, "user": request.state.user, "doors": doors}
    )


@router.post("/process")
def process_scan(
    payload: ScanRequest,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(deps.require_exit_access),
):
    try:
        outcome = record_exit(
            db,
            qr_code=payload.qr_code,
            door_id=payload.door_id,
            operator=user,
        )
    except Exception:
        logger.exception("Error inesperado al procesar una salida")
        return JSONResponse(
            status_code=500,
            content=ScanResponse(
                status="error",
                message="ERROR INTERNO AL REGISTRAR LA SALIDA",
            ).model_dump(),
        )

    student_info = None
    if outcome.student is not None:
        student_info = StudentInfo(
            name=outcome.student.full_name,
            course=outcome.student.course,
            photo=photo_url(outcome.student.photo_path, "students"),
        )

    body = ScanResponse(
        status=outcome.status,
        message=outcome.message,
        timestamp=outcome.timestamp,
        previous_timestamp=outcome.previous_timestamp,
        student=student_info,
    )
    return JSONResponse(status_code=outcome.http_status, content=body.model_dump())
