from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.requests import Request
from .. import database, models, deps, auth
from ..services.audit import add_audit

router = APIRouter(
    prefix="/users",
    tags=["Users"],
    dependencies=[Depends(deps.require_admin)],  # ¡Solo Admins pueden entrar aquí!
)

templates = Jinja2Templates(directory="app/templates")


def _redirect(message: str, *, error: bool = False, status_code: int = 303) -> RedirectResponse:
    key = "error" if error else "msg"
    return RedirectResponse(url=f"/users?{key}={quote_plus(message)}", status_code=status_code)


def _role_from_form(role: str) -> models.UserRole:
    try:
        return models.UserRole(role)
    except ValueError:
        try:
            return models.UserRole[role.strip().upper()]
        except KeyError as exc:
            raise ValueError("Rol inválido") from exc


def _active_admin_count(db: Session, *, exclude_id: int | None = None) -> int:
    query = db.query(models.User).filter(
        models.User.role == models.UserRole.ADMIN,
        models.User.is_active.is_(True),
    )
    if exclude_id is not None:
        query = query.filter(models.User.id != exclude_id)
    return query.count()


def _user_has_history(db: Session, user_id: int) -> bool:
    references = (
        (models.ExitLog, models.ExitLog.operator_id),
        (models.LunchLog, models.LunchLog.operator_id),
        (models.ScanAttempt, models.ScanAttempt.operator_id),
        (models.AuditLog, models.AuditLog.actor_id),
    )
    return any(
        db.query(model).filter(column == user_id).first() is not None
        for model, column in references
    )


@router.get("/")
def list_users(request: Request, db: Session = Depends(database.get_db)):
    users = db.query(models.User).all()
    return templates.TemplateResponse(
        "users.html", {"request": request, "users": users, "user": request.state.user}
    )


@router.post("/create")
def create_user(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(database.get_db),
):
    username = username.strip()
    if not username:
        return _redirect("El usuario no puede estar vacío", error=True)

    # Verificar duplicado
    if db.query(models.User).filter(models.User.username == username).first():
        return _redirect("El usuario ya existe", error=True)

    try:
        role_enum = _role_from_form(role)
        auth.validate_password(password, username=username)
    except ValueError as exc:
        return _redirect(str(exc), error=True)

    new_user = models.User(
        username=username,
        full_name=full_name.strip(),
        hashed_password=auth.get_password_hash(password),
        role=role_enum,
    )
    db.add(new_user)
    db.flush()
    add_audit(
        db,
        action="user.created",
        actor_id=request.state.user.id,
        entity_type="user",
        entity_id=new_user.id,
        details={"username": new_user.username, "role": role_enum.value},
        request=request,
    )
    db.commit()
    return _redirect("Usuario creado")


@router.post("/update")
def update_user(
    request: Request,
    user_id: int = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
    password: str = Form(None),  # Opcional
    db: Session = Depends(database.get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        return _redirect("Usuario no encontrado", error=True)

    try:
        role_enum = _role_from_form(role)
    except ValueError as exc:
        return _redirect(str(exc), error=True)

    previous_role = user.role
    if (
        user.is_active
        and previous_role == models.UserRole.ADMIN
        and role_enum != models.UserRole.ADMIN
        and _active_admin_count(db, exclude_id=user.id) == 0
    ):
        return _redirect("No puedes quitar el rol al último administrador activo", error=True)

    password_changed = bool(password and password.strip())
    if password_changed:
        try:
            auth.validate_password(password, username=user.username)
        except ValueError as exc:
            return _redirect(str(exc), error=True)

    user.full_name = full_name.strip()
    user.role = role_enum

    # Si se envió contraseña, actualizarla e invalidar sesiones previas
    if password_changed:
        user.hashed_password = auth.get_password_hash(password)
        user.must_change_password = False

    # Rol o contraseña nuevos deben invalidar los tokens emitidos con los valores anteriores
    if password_changed or role_enum != previous_role:
        user.token_version = (user.token_version or 0) + 1

    add_audit(
        db,
        action="user.updated",
        actor_id=request.state.user.id,
        entity_type="user",
        entity_id=user.id,
        details={
            "username": user.username,
            "previous_role": previous_role.value if previous_role else None,
            "new_role": role_enum.value,
            "password_reset": password_changed,
        },
        request=request,
    )
    db.commit()
    return _redirect("Usuario actualizado")


@router.post("/delete/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(database.get_db)):
    # Evitar auto-borrado
    if request.state.user.id == user_id:
        return _redirect("No puedes borrarte a ti mismo", error=True)

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        return _redirect("Usuario no encontrado", error=True)

    if (
        user.is_active
        and user.role == models.UserRole.ADMIN
        and _active_admin_count(db, exclude_id=user.id) == 0
    ):
        return _redirect("No puedes eliminar al último administrador activo", error=True)

    has_history = _user_has_history(db, user.id)
    username = user.username
    role_value = user.role.value if user.role else None

    user.token_version = (user.token_version or 0) + 1
    if has_history:
        user.is_active = False
        action = "user.deactivated"
        message = "Usuario desactivado para conservar el historial"
    else:
        db.delete(user)
        action = "user.deleted"
        message = "Usuario eliminado"

    add_audit(
        db,
        action=action,
        actor_id=request.state.user.id,
        entity_type="user",
        entity_id=user_id,
        details={"username": username, "role": role_value},
        request=request,
    )
    db.commit()
    return _redirect(message)
