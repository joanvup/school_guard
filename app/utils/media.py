from pathlib import Path
from urllib.parse import quote

from ..config import settings

PHOTO_SCOPES = {"students", "employees"}
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}


def photo_filename(value: str | None) -> str | None:
    if not value:
        return None
    name = Path(str(value).replace("\\", "/")).name.strip()
    if not name or Path(name).suffix.lower() not in PHOTO_SUFFIXES:
        return None
    return name


def photo_url(value: str | None, scope: str) -> str | None:
    name = photo_filename(value)
    if not name or scope not in PHOTO_SCOPES:
        return None
    return f"/media/photos/{scope}/{quote(name)}"


def photo_file(value: str | None, scope: str) -> Path | None:
    name = photo_filename(value)
    if not name or scope not in PHOTO_SCOPES:
        return None
    base = (settings.media_photos_dir / scope).resolve()
    path = (base / name).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        return None
    return path
