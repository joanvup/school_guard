import io
import zipfile

import pytest
from PIL import Image

from app.config import settings
from app.utils import media


class _Upload:
    def __init__(self, data: bytes):
        self.file = io.BytesIO(data)


def _image(mode: str, image_format: str, color=1, size=(8, 8)) -> bytes:
    output = io.BytesIO()
    Image.new(mode, size, color).save(output, format=image_format)
    return output.getvalue()


PNG = _image("RGB", "PNG", "white")


def _zip_bytes(entries: dict[str, bytes], *, stored: bool = False) -> bytes:
    output = io.BytesIO()
    method = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(output, "w", method) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_normalize_rejects_images_above_pixel_limit(monkeypatch):
    monkeypatch.setattr(media, "MAX_IMAGE_PIXELS", 10)

    with pytest.raises(media.UploadError):
        media.normalize_photo_bytes(PNG)


def test_normalize_rejects_image_that_fails_second_decode(monkeypatch):
    real_open = media.Image.open
    calls = {"count": 0}

    def flaky_open(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_open(*args, **kwargs)
        raise OSError("segunda apertura fallida")

    monkeypatch.setattr(media.Image, "open", flaky_open)

    with pytest.raises(media.UploadError):
        media.normalize_photo_bytes(PNG)


def test_normalize_converts_cmyk_grayscale_and_palette_images():
    cmyk_data, cmyk_suffix = media.normalize_photo_bytes(_image("CMYK", "JPEG", (0, 0, 0, 0)))
    assert cmyk_suffix == ".jpg"
    with Image.open(io.BytesIO(cmyk_data)) as image:
        assert image.mode == "RGB"

    gray_data, gray_suffix = media.normalize_photo_bytes(_image("L", "JPEG", 128))
    assert gray_suffix == ".jpg"
    with Image.open(io.BytesIO(gray_data)) as image:
        assert image.mode == "RGB"

    palette_data, palette_suffix = media.normalize_photo_bytes(_image("P", "PNG", 1))
    assert palette_suffix == ".png"
    with Image.open(io.BytesIO(palette_data)) as image:
        assert image.mode == "RGB"


def test_normalize_rejects_encoded_output_over_limit():
    with pytest.raises(media.UploadError):
        media.normalize_photo_bytes(PNG, max_bytes=10)


def test_safe_stem_removes_unsafe_characters():
    assert media.safe_stem(None) == ""
    assert media.safe_stem("!!!") == ""
    assert media.safe_stem("S 400") == "S_400"


def test_store_photo_validates_scope_stem_and_path(monkeypatch):
    with pytest.raises(media.UploadError):
        media.store_photo("otro", "S400", b"data", ".png")

    with pytest.raises(media.UploadError):
        media.store_photo("students", "!!!", b"data", ".png")

    monkeypatch.setattr(media, "safe_stem", lambda value: "../escape")
    with pytest.raises(media.UploadError):
        media.store_photo("students", "S400", b"data", ".png")


def test_validate_zip_name_rejects_unsafe_names():
    assert media._validate_zip_name("ok.png") == "ok.png"

    for unsafe in ("", "\x00", "/etc/passwd", ".hidden"):
        with pytest.raises(media.UploadError):
            media._validate_zip_name(unsafe)


def test_read_zip_entries_skips_directories_hidden_and_duplicates():
    data = _zip_bytes(
        {
            "folder/": b"",
            ".hidden.png": PNG,
            "__MACOSX/._x.png": PNG,
            "a/photo.png": PNG,
            "b/photo.png": PNG,
            "ok.png": PNG,
        }
    )

    entries = media.read_zip_entries(_Upload(data))

    assert [name for name, _ in entries] == ["photo.png", "ok.png"]


def test_read_zip_entries_wraps_invalid_archives():
    with pytest.raises(media.UploadError):
        media.read_zip_entries(_Upload(b"no soy un zip"))


def test_read_zip_entries_rejects_encrypted_entries():
    data = bytearray(_zip_bytes({"S1.png": PNG}))
    central = data.find(b"PK\x01\x02")
    assert central != -1
    flags = int.from_bytes(data[central + 8 : central + 10], "little") | 1
    data[central + 8 : central + 10] = flags.to_bytes(2, "little")

    with pytest.raises(media.UploadError):
        media.read_zip_entries(_Upload(bytes(data)))


def test_read_zip_entries_rejects_suspicious_compression_ratio():
    data = _zip_bytes({"bomb.png": b"\0" * 100_000})

    with pytest.raises(media.UploadError):
        media.read_zip_entries(_Upload(data))


def test_read_zip_entries_rejects_total_uncompressed_size(monkeypatch):
    monkeypatch.setattr(media, "MAX_COMPRESSION_RATIO", 10**9)
    monkeypatch.setattr(settings, "max_zip_total_mb", 1)
    data = _zip_bytes({"a.png": b"\0" * 600_000, "b.png": b"\0" * 600_000})

    with pytest.raises(media.UploadError):
        media.read_zip_entries(_Upload(data))


def test_read_zip_entries_wraps_member_read_errors(monkeypatch):
    data = _zip_bytes({"S1.png": PNG})

    def fail_open(self, *args, **kwargs):
        raise OSError("lectura fallida")

    monkeypatch.setattr(zipfile.ZipFile, "open", fail_open)

    with pytest.raises(media.UploadError):
        media.read_zip_entries(_Upload(data))


def test_read_zip_entries_rejects_content_above_limit_after_read(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    data = _zip_bytes({"S1.png": PNG})

    class FakeHandle:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, size):
            return b"x" * (1024 * 1024 + 1)

    monkeypatch.setattr(zipfile.ZipFile, "open", lambda self, *args, **kwargs: FakeHandle())

    with pytest.raises(media.UploadError):
        media.read_zip_entries(_Upload(data))


def test_zip_photo_entries_skips_non_images_and_invalid_data():
    data = _zip_bytes(
        {
            "nota.txt": b"hola",
            "rota.png": b"no soy imagen",
            "valida.png": PNG,
        }
    )

    photos = media.zip_photo_entries(_Upload(data))

    assert [name for name, _, _ in photos] == ["valida"]
    assert photos[0][2] == ".png"


def test_photo_url_builds_scoped_media_links():
    assert media.photo_url("S400.png", "students") == "/media/photos/students/S400.png"
    assert media.photo_url("S400.png", "otro") is None
    assert media.photo_url("..", "students") is None
