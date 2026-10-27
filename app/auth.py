import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt
from passlib.context import CryptContext

from .config import settings
from .services.qr import sign_qr_content, sign_qr_v1_with_key, verify_qr_content

__all__ = [
    "DUMMY_HASH",
    "LoginRateLimiter",
    "create_access_token",
    "get_password_hash",
    "login_limiter",
    "sign_qr_content",
    "validate_password",
    "verify_password",
    "verify_qr_content",
]

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
DUMMY_HASH = pwd_context.hash("dummy-password-for-timing")

COMMON_PASSWORDS = {
    "123456789012",
    "contrasena123",
    "contraseña123",
    "password1234",
    "qwertyuiop12",
    "administrador",
    "administrador123",
    "colegio123456",
    "schoolguard123",
    "passwordpassword",
    "1234567890ab",
}


def validate_password(password: str, *, username: str | None = None) -> None:
    if not password or password != password.strip():
        raise ValueError(
            "La contraseña no puede estar vacía ni tener espacios al inicio o al final"
        )
    minimum = settings.password_min_length
    if len(password) < minimum:
        raise ValueError(f"La contraseña debe tener al menos {minimum} caracteres")
    if len(password) > 128:
        raise ValueError("La contraseña no puede superar los 128 caracteres")
    if password.lower() in COMMON_PASSWORDS:
        raise ValueError("La contraseña es demasiado común; elija otra")
    if username and username.strip() and username.strip().lower() in password.lower():
        raise ValueError("La contraseña no puede contener el nombre de usuario")
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        raise ValueError("La contraseña debe incluir letras y números")
    if len(set(password)) < 5:
        raise ValueError("La contraseña es demasiado simple")


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
    """Firma v1 con una clave concreta; se usa en pruebas de rotación."""
    return sign_qr_v1_with_key(student_id, key).rsplit(".", 1)[1]


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
