import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, status

from .config import settings

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_TOKEN_MAX_AGE = 12 * 60 * 60

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
FORM_CONTENT_TYPES = (
    "application/x-www-form-urlencoded",
    "multipart/form-data",
)


def _signature(nonce: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        nonce.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_token() -> str:
    nonce = secrets.token_urlsafe(32)
    return f"{nonce}.{_signature(nonce)}"


def is_valid_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    nonce, signature = token.split(".", 1)
    if not nonce or not signature:
        return False
    return hmac.compare_digest(_signature(nonce), signature)


def get_or_create_token(request: Request) -> str:
    token = request.cookies.get(CSRF_COOKIE_NAME)
    if is_valid_token(token):
        return token
    return generate_token()


async def _submitted_token(request: Request) -> str | None:
    token = request.headers.get(CSRF_HEADER_NAME)
    if token:
        return token

    content_type = request.headers.get("content-type", "")
    if content_type.startswith(FORM_CONTENT_TYPES):
        form = await request.form()
        value = form.get(CSRF_FORM_FIELD)
        if isinstance(value, str):
            return value
    return None


async def verify_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    submitted = await _submitted_token(request)
    valid = (
        submitted is not None
        and cookie_token is not None
        and hmac.compare_digest(submitted, cookie_token)
        and is_valid_token(cookie_token)
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token CSRF inválido o ausente",
        )


async def csrf_cookie_middleware(request: Request, call_next):
    token = get_or_create_token(request)
    request.state.csrf_token = token

    response = await call_next(request)

    if request.cookies.get(CSRF_COOKIE_NAME) != token:
        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=token,
            max_age=CSRF_TOKEN_MAX_AGE,
            httponly=False,
            secure=settings.cookie_secure_effective,
            samesite="lax",
            path="/",
        )
    return response
