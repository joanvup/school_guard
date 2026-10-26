from datetime import time as dt_time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    database_url: str = Field(alias="DATABASE_URL")
    secret_key: str = Field(alias="SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="ALGORITHM")
    access_token_expire_minutes: int = Field(
        default=120, alias="ACCESS_TOKEN_EXPIRE_MINUTES", ge=5, le=1440
    )

    qr_secret_key_current: str = Field(
        validation_alias=AliasChoices("QR_SECRET_KEY_CURRENT", "QR_SECRET_KEY")
    )
    qr_secret_key_previous: str | None = Field(default=None, alias="QR_SECRET_KEY_PREVIOUS")

    cookie_secure: bool | None = Field(default=None, alias="COOKIE_SECURE")
    timezone: str = Field(default="America/Bogota", alias="TIMEZONE")
    cooldown_minutes: int = Field(default=15, alias="COOLDOWN_MINUTES", ge=0, le=1440)

    login_max_attempts: int = Field(default=5, alias="LOGIN_MAX_ATTEMPTS", ge=1, le=100)
    login_lockout_minutes: int = Field(default=5, alias="LOGIN_LOCKOUT_MINUTES", ge=1, le=1440)

    lunch_window_start: str = Field(default="11:00", alias="LUNCH_WINDOW_START")
    lunch_window_end: str = Field(default="14:00", alias="LUNCH_WINDOW_END")
    lunch_window_enforcement: Literal["off", "warn", "deny"] = Field(
        default="off", alias="LUNCH_WINDOW_ENFORCEMENT"
    )

    csp_mode: Literal["enforce", "report-only", "off"] = Field(default="enforce", alias="CSP_MODE")
    hsts_max_age: int = Field(default=31536000, alias="HSTS_MAX_AGE", ge=0)

    bootstrap_admin_password: str | None = Field(default=None, alias="BOOTSTRAP_ADMIN_PASSWORD")
    media_photos_dir: Path = Field(
        default=BASE_DIR / "app" / "data" / "photos", alias="MEDIA_PHOTOS_DIR"
    )

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("DATABASE_URL no puede estar vacío")
        return value

    @field_validator("secret_key")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        if not value:
            raise ValueError("SECRET_KEY es obligatorio")
        return value

    @field_validator("qr_secret_key_current")
    @classmethod
    def _validate_qr_key(cls, value: str) -> str:
        if not value:
            raise ValueError("QR_SECRET_KEY_CURRENT es obligatorio")
        return value

    @field_validator("algorithm")
    @classmethod
    def _validate_algorithm(cls, value: str) -> str:
        if value != "HS256":
            raise ValueError("ALGORITHM debe ser HS256")
        return value

    @field_validator("lunch_window_start", "lunch_window_end")
    @classmethod
    def _validate_window_time(cls, value: str) -> str:
        try:
            dt_time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("La ventana de almuerzo debe usar HH:MM") from exc
        return value

    @model_validator(mode="after")
    def _validate_rotation(self) -> "Settings":
        if (
            self.qr_secret_key_previous
            and self.qr_secret_key_previous == self.qr_secret_key_current
        ):
            raise ValueError("QR_SECRET_KEY_PREVIOUS debe ser distinta de QR_SECRET_KEY_CURRENT")
        if dt_time.fromisoformat(self.lunch_window_start) >= dt_time.fromisoformat(
            self.lunch_window_end
        ):
            raise ValueError("LUNCH_WINDOW_START debe ser anterior a LUNCH_WINDOW_END")
        return self

    @property
    def lunch_window_times(self) -> tuple[dt_time, dt_time]:
        return dt_time.fromisoformat(self.lunch_window_start), dt_time.fromisoformat(
            self.lunch_window_end
        )

    @property
    def cookie_secure_effective(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_env == "production"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
