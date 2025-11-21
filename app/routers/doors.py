from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.requests import Request
from .. import database, models, deps

router = APIRouter(
    prefix="/doors",
    tags=["Doors"],
    dependencies=[Depends(deps.require_admin)]
)

templates = Jinja2Templates(directory="app/templates")

@router.get("/")
def list_doors(request: Request, db: Session = Depends(database.get_db)):
    doors = db.query(models.Door).all()
    return templates.TemplateResponse("doors.html", {"request": request, "doors": doors, "user": request.state.user})

@router.post("/create")
def create_door(
    name: str = Form(...),
    description: str = Form(None),
    db: Session = Depends(database.get_db)
):
    existing = db.query(models.Door).filter(models.Door.name == name).first()
    if existing:
        return RedirectResponse(url="/doors?error=Nombre+ya+existe", status_code=303)
    
    new_door = models.Door(name=name, description=description)
    db.add(new_door)
    db.commit()
    return RedirectResponse(url="/doors", status_code=303)

@router.get("/delete/{id}")
def delete_door(id: int, db: Session = Depends(database.get_db)):
    # En un sistema real, quizás solo la desactivaríamos si tiene logs asociados
    door = db.query(models.Door).filter(models.Door.id == id).first()
    if door:
        db.delete(door)
        db.commit()
    return RedirectResponse(url="/doors", status_code=303)

@router.get("/toggle/{id}")
def toggle_door(id: int, db: Session = Depends(database.get_db)):
    door = db.query(models.Door).filter(models.Door.id == id).first()
    if door:
        door.is_active = not door.is_active
        db.commit()
    return RedirectResponse(url="/doors", status_code=303)