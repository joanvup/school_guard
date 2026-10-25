from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import auth, database, models
from ..config import settings

router = APIRouter(tags=["Authentication"])
templates = Jinja2Templates(directory="app/templates")

GENERIC_LOGIN_ERROR = "Usuario o contraseña incorrectos"
LOCKED_LOGIN_ERROR = "Demasiados intentos fallidos. Intente de nuevo en unos minutos."


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    if request.state.user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(database.get_db),
):
    ip = _client_ip(request)
    username = username.strip()
    now_utc = _utcnow_naive()

    if auth.login_limiter.is_blocked(ip, username):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": LOCKED_LOGIN_ERROR},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    user = db.query(models.User).filter(models.User.username == username).first()

    if user and user.locked_until and user.locked_until > now_utc:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": LOCKED_LOGIN_ERROR},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    password_ok = auth.verify_password(password, user.hashed_password if user else auth.DUMMY_HASH)

    if not user or not password_ok or not user.is_active:
        if user:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= settings.login_max_attempts:
                user.locked_until = now_utc + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_count = 0
            db.commit()
        auth.login_limiter.register_failure(ip, username)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": GENERIC_LOGIN_ERROR},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    auth.login_limiter.reset(ip, username)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now_utc
    db.commit()

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = auth.create_access_token(
        data={
            "sub": user.username,
            "role": user.role.value,
            "ver": user.token_version,
        },
        expires_delta=access_token_expires,
    )

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure_effective,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(
        "access_token",
        path="/",
        httponly=True,
        secure=settings.cookie_secure_effective,
        samesite="lax",
    )
    return response
