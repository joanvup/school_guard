import io
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import settings

PHOTO_SCOPES = {"students", "employees"}
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}
IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png"}
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_SIDE = 1600
MAX_COMPRESSION_RATIO = 200
_SAFE_STEM = re.compile(r"[^A-Za-z0-9_-]+")


class UploadError(ValueError):
    """Archivo subido inválido o fuera de los límites permitidos."""


def _max_upload_bytes() -> int:
    return settings.max_upload_mb * 1024 * 1024


def read_upload(upload, *, max_bytes: int | None = None) -> bytes:
    limit = max_bytes or _max_upload_bytes()
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise UploadError(f"El archivo supera el límite de {limit // (1024 * 1024)} MB")
    if not data:
        raise UploadError("El archivo está vacío")
    return data


def _load_image(data: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(data)) as probe:
            width, height = probe.size
            image_format = probe.format
            if image_format not in IMAGE_FORMATS:
                raise UploadError("Solo se permiten imágenes JPG o PNG")
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise UploadError("La imagen excede el tamaño de píxeles permitido")
            probe.verify()
    except UploadError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise UploadError("El archivo no es una imagen válida") from exc

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise UploadError("El archivo no es una imagen válida") from exc
    return image


def _encode_image(image: Image.Image, suffix: str, *, max_bytes: int) -> bytes:
    if image.mode not in ("RGB", "L", "RGBA"):
        image = image.convert("RGB")
    image = ImageOps.exif_transpose(image)
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)

    output = io.BytesIO()
    if suffix == ".jpg":
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.save(output, format="JPEG", quality=85, optimize=True)
    else:
        if image.mode not in ("RGB", "RGBA", "L"):
            image = image.convert("RGBA")
        image.save(output, format="PNG", optimize=True)

    result = output.getvalue()
    if len(result) > max_bytes:
        raise UploadError("La imagen procesada supera el límite de tamaño")
    return result


def normalize_photo_bytes(data: bytes, *, max_bytes: int | None = None) -> tuple[bytes, str]:
    limit = max_bytes or _max_upload_bytes()
    image = _load_image(data)
    suffix = IMAGE_FORMATS[image.format]
    return _encode_image(image, suffix, max_bytes=limit), suffix


def normalize_photo(upload) -> tuple[bytes, str]:
    return normalize_photo_bytes(read_upload(upload))


def safe_stem(value: str | None) -> str:
    if not value:
        return ""
    return _SAFE_STEM.sub("_", str(value).strip())[:100].strip("_")


def store_photo(scope: str, stem: str, data: bytes, suffix: str) -> str:
    if scope not in PHOTO_SCOPES or suffix not in {".jpg", ".png"}:
        raise UploadError("Alcance o formato de foto inválido")
    clean_stem = safe_stem(stem)
    if not clean_stem:
        raise UploadError("El identificador de la foto no es válido")

    base = (settings.media_photos_dir / scope).resolve()
    base.mkdir(parents=True, exist_ok=True)
    filename = f"{clean_stem}{suffix}"
    path = (base / filename).resolve()
    if not path.is_relative_to(base):
        raise UploadError("Ruta de foto no permitida")
    path.write_bytes(data)
    return filename


def _validate_zip_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    if not normalized or "\x00" in normalized:
        raise UploadError("El ZIP contiene nombres no válidos")
    parts = Path(normalized).parts
    if normalized.startswith("/") or Path(normalized).is_absolute():
        raise UploadError("El ZIP contiene rutas no permitidas")
    if any(part in {"..", "."} for part in parts):
        raise UploadError("El ZIP contiene rutas no permitidas")
    base = parts[-1]
    if base.startswith("."):
        raise UploadError("El ZIP contiene archivos ocultos")
    return base


def read_zip_entries(upload) -> list[tuple[str, bytes]]:
    total_limit = settings.max_zip_total_mb * 1024 * 1024
    entry_limit = _max_upload_bytes()
    data = read_upload(upload, max_bytes=total_limit)

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise UploadError("El archivo no es un ZIP válido") from exc

    with archive:
        infos = []
        total_size = 0
        seen_names: set[str] = set()
        for info in archive.infolist():
            if info.is_dir():
                continue
            raw_name = info.filename.replace("\\", "/")
            base = Path(raw_name).name
            if "__MACOSX" in raw_name or base.startswith((".", "__")):
                continue
            _validate_zip_name(info.filename)
            if base in seen_names:
                continue
            if info.flag_bits & 0x1:
                raise UploadError("El ZIP no puede contener archivos cifrados")
            if info.file_size > entry_limit:
                raise UploadError("Una imagen del ZIP supera el límite de tamaño")
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > MAX_COMPRESSION_RATIO:
                raise UploadError("El ZIP parece contener datos comprimidos de forma anómala")
            total_size += info.file_size
            if total_size > total_limit:
                raise UploadError("El contenido del ZIP supera el límite permitido")
            infos.append((info.filename, info))
            seen_names.add(base)

        if len(infos) > settings.max_zip_entries:
            raise UploadError("El ZIP contiene demasiados archivos")

        entries = []
        for member_name, info in infos:
            try:
                with archive.open(info) as handle:
                    content = handle.read(entry_limit + 1)
            except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
                raise UploadError("No se pudo leer el contenido del ZIP") from exc
            if len(content) > entry_limit:
                raise UploadError("Una imagen del ZIP supera el límite de tamaño")
            entries.append((_validate_zip_name(member_name), content))
    return entries


def zip_photo_entries(upload) -> list[tuple[str, bytes, str]]:
    photos = []
    for name, content in read_zip_entries(upload):
        if Path(name).suffix.lower() not in PHOTO_SUFFIXES:
            continue
        try:
            data, suffix = normalize_photo_bytes(content)
        except UploadError:
            continue
        photos.append((Path(name).stem, data, suffix))
    return photos


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
