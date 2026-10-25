from fastapi import Depends, HTTPException, status, Request
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from . import database, models
from .config import settings
from .models import UserRole


def get_current_user(request: Request, db: Session = Depends(database.get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None

    try:
        scheme, _, param = token.partition(" ")
        if scheme != "Bearer" or not param:
            return None
        payload = jwt.decode(param, settings.secret_key, algorithms=[settings.algorithm])
        username: str = payload.get("sub")
        if username is None:
            return None
        token_version = payload.get("ver", 0)
    except JWTError:
        return None

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None or not user.is_active:
        return None
    if token_version != (user.token_version or 0):
        return None
    return user


def require_user(user: models.User = Depends(get_current_user)):
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
        )
    return user


def require_admin(user: models.User = Depends(require_user)):
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos de administrador",
        )
    return user


def require_lunch_access(user: models.User = Depends(require_user)):
    if user.role not in [models.UserRole.ADMIN, models.UserRole.LUNCH_OP]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere acceso a Comedor",
        )
    return user


def require_exit_access(user: models.User = Depends(require_user)):
    if user.role not in [models.UserRole.ADMIN, models.UserRole.OPERATOR]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere acceso a Portería",
        )
    return user
