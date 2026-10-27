from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.requests import Request
from .. import database, models, deps
from ..services.audit import add_audit

router = APIRouter(prefix="/doors", tags=["Doors"], dependencies=[Depends(deps.require_admin)])

templates = Jinja2Templates(directory="app/templates")


def _redirect(message: str, *, error: bool = False) -> RedirectResponse:
    key = "error" if error else "msg"
    return RedirectResponse(url=f"/doors?{key}={quote_plus(message)}", status_code=303)


def _door_has_history(db: Session, door_id: int) -> bool:
    return any(
        db.query(model).filter(column == door_id).first() is not None
        for model, column in (
            (models.ExitLog, models.ExitLog.door_id),
            (models.ScanAttempt, models.ScanAttempt.door_id),
        )
    )


def _other_active_doors(db: Session, door_id: int) -> int:
    return (
        db.query(models.Door)
        .filter(models.Door.is_active.is_(True), models.Door.id != door_id)
        .count()
    )


@router.get("/")
def list_doors(request: Request, db: Session = Depends(database.get_db)):
    doors = db.query(models.Door).all()
    return templates.TemplateResponse(
        "doors.html", {"request": request, "doors": doors, "user": request.state.user}
    )


@router.post("/create")
def create_door(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    db: Session = Depends(database.get_db),
):
    name = name.strip()
    if not name:
        return _redirect("El nombre de la puerta es obligatorio", error=True)

    existing = db.query(models.Door).filter(models.Door.name == name).first()
    if existing:
        return _redirect("Nombre ya existe", error=True)

    new_door = models.Door(name=name, description=description)
    db.add(new_door)
    db.flush()
    add_audit(
        db,
        action="door.created",
        actor_id=request.state.user.id,
        entity_type="door",
        entity_id=new_door.id,
        details={"name": new_door.name},
        request=request,
    )
    db.commit()
    return _redirect("Puerta creada")


@router.post("/delete/{id}")
def delete_door(id: int, request: Request, db: Session = Depends(database.get_db)):
    door = db.query(models.Door).filter(models.Door.id == id).first()
    if not door:
        return _redirect("Puerta no encontrada", error=True)

    if door.is_active and _other_active_doors(db, door.id) == 0:
        return _redirect("Debe existir al menos una puerta activa", error=True)

    has_history = _door_has_history(db, door.id)
    door_name = door.name
    if has_history:
        door.is_active = False
        action = "door.deactivated"
        message = "Puerta desactivada para conservar el historial"
    else:
        db.delete(door)
        action = "door.deleted"
        message = "Puerta eliminada"

    add_audit(
        db,
        action=action,
        actor_id=request.state.user.id,
        entity_type="door",
        entity_id=id,
        details={"name": door_name},
        request=request,
    )
    db.commit()
    return _redirect(message)


@router.post("/toggle/{id}")
def toggle_door(id: int, request: Request, db: Session = Depends(database.get_db)):
    door = db.query(models.Door).filter(models.Door.id == id).first()
    if not door:
        return _redirect("Puerta no encontrada", error=True)

    if door.is_active and _other_active_doors(db, door.id) == 0:
        return _redirect("Debe existir al menos una puerta activa", error=True)

    previous = bool(door.is_active)
    door.is_active = not previous
    add_audit(
        db,
        action="door.updated",
        actor_id=request.state.user.id,
        entity_type="door",
        entity_id=door.id,
        details={
            "name": door.name,
            "previous_active": previous,
            "new_active": bool(door.is_active),
        },
        request=request,
    )
    db.commit()
    return _redirect("Puerta actualizada")
