from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.requests import Request
from .. import database, models, deps, auth

router = APIRouter(
    prefix="/users",
    tags=["Users"],
    dependencies=[Depends(deps.require_admin)] # ¡Solo Admins pueden entrar aquí!
)

templates = Jinja2Templates(directory="app/templates")

@router.get("/")
def list_users(request: Request, db: Session = Depends(database.get_db)):
    users = db.query(models.User).all()
    return templates.TemplateResponse("users.html", {
        "request": request, 
        "users": users, 
        "user": request.state.user
    })

@router.post("/create")
def create_user(
    username: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(database.get_db)
):
    # Verificar duplicado
    if db.query(models.User).filter(models.User.username == username).first():
        return RedirectResponse(url="/users?error=El+usuario+ya+existe", status_code=303)
    
    hashed_pw = auth.get_password_hash(password)
    
    new_user = models.User(
        username=username,
        full_name=full_name,
        hashed_password=hashed_pw,
        role=role
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/users?msg=Usuario+creado", status_code=303)

@router.post("/update")
def update_user(
    user_id: int = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
    password: str = Form(None), # Opcional
    db: Session = Depends(database.get_db)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        return RedirectResponse(url="/users?error=Usuario+no+encontrado", status_code=303)
    
    user.full_name = full_name
    user.role = role
    
    # Si se envió contraseña, actualizarla
    if password and password.strip():
        user.hashed_password = auth.get_password_hash(password)
        
    db.commit()
    return RedirectResponse(url="/users?msg=Usuario+actualizado", status_code=303)

@router.get("/delete/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(database.get_db)):
    # Evitar auto-borrado
    if request.state.user.id == user_id:
        return RedirectResponse(url="/users?error=No+puedes+borrarte+a+ti+mismo", status_code=303)
        
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()
    return RedirectResponse(url="/users?msg=Usuario+eliminado", status_code=303)