import hashlib
import hmac
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt
from passlib.context import CryptContext

from .config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
DUMMY_HASH = pwd_context.hash("dummy-password-for-timing")


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def _sign_qr(student_id: str, key: str) -> str:
    signature = hmac.new(
        key.encode("utf-8"), student_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return signature[:16]


def sign_qr_content(student_id: str) -> str:
    """Genera un string firmado: ID.FIRMA (primeros 16 hex del HMAC)."""
    return f"{student_id}.{_sign_qr(student_id, settings.qr_secret_key_current)}"


def verify_qr_content(qr_content: str) -> str | None:
    """Verifica la firma con la clave actual o la anterior y retorna el ID limpio."""
    if not qr_content or "." not in qr_content:
        return None

    student_id, received_sig = qr_content.split(".", 1)
    if not student_id or len(received_sig) != 16:
        return None

    keys = [settings.qr_secret_key_current]
    if settings.qr_secret_key_previous:
        keys.append(settings.qr_secret_key_previous)

    for key in keys:
        expected_sig = _sign_qr(student_id, key)
        if hmac.compare_digest(expected_sig, received_sig):
            return student_id
    return None


class LoginRateLimiter:
    """Límite de intentos fallidos en memoria, por IP + usuario.

    En Fase 1 se sustituye por un bloqueo persistido en base de datos para
    que funcione con varios workers.
    """

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(ip: str, username: str) -> str:
        return f"{ip}|{username.strip().lower()}"

    def is_blocked(self, ip: str, username: str) -> bool:
        now = time.monotonic()
        key = self._key(ip, username)
        with self._lock:
            self._prune(now)
            attempts = self._attempts.get(key, [])
            return len(attempts) >= self.max_attempts

    def register_failure(self, ip: str, username: str) -> None:
        now = time.monotonic()
        key = self._key(ip, username)
        with self._lock:
            self._prune(now)
            attempts = self._attempts.setdefault(key, [])
            attempts.append(now)
            if len(attempts) > self.max_attempts:
                del attempts[: len(attempts) - self.max_attempts]

    def reset(self, ip: str, username: str) -> None:
        key = self._key(ip, username)
        with self._lock:
            self._attempts.pop(key, None)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        expired = [
            key
            for key, attempts in self._attempts.items()
            if not attempts or attempts[-1] <= cutoff
        ]
        for key in expired:
            self._attempts.pop(key, None)


login_limiter = LoginRateLimiter(
    max_attempts=settings.login_max_attempts,
    window_seconds=settings.login_lockout_minutes * 60,
)
