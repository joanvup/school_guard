"""Mueve las fotos públicas antiguas al directorio privado y protegido.

Uso (desde la raíz del proyecto, con la aplicación detenida):

    python scripts/migrate_photos.py

No elimina archivos: si el destino ya existe, conserva ambos y lo informa.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Employee, Student  # noqa: E402
from app.utils.media import photo_filename  # noqa: E402

LEGACY_DIR = Path("app/static/photos")
SUFFIXES = {".jpg", ".jpeg", ".png"}


def _db_photo_names() -> tuple[set[str], set[str]]:
    db = SessionLocal()
    try:
        students = {
            name for (path,) in db.query(Student.photo_path).all() if (name := photo_filename(path))
        }
        employees = {
            name
            for (path,) in db.query(Employee.photo_path).all()
            if (name := photo_filename(path))
        }
        return students, employees
    finally:
        db.close()


def main() -> int:
    if not LEGACY_DIR.is_dir():
        print("No existe app/static/photos; nada que mover.")
        return 0

    student_names, employee_names = _db_photo_names()
    moved = 0
    skipped = 0

    for source in sorted(LEGACY_DIR.iterdir()):
        if not source.is_file() or source.suffix.lower() not in SUFFIXES:
            continue
        if source.name in employee_names or source.name.startswith("EMP_"):
            scope = "employees"
        elif source.name in student_names:
            scope = "students"
        else:
            print(f"OMITIDA (no está vinculada en la BD): {source.name}")
            skipped += 1
            continue

        target = settings.media_photos_dir / scope / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            print(f"OMITIDA (ya existe en destino): {source.name}")
            skipped += 1
            continue

        shutil.move(str(source), str(target))
        moved += 1

    print(f"Movidas: {moved}; omitidas: {skipped}.")
    try:
        LEGACY_DIR.rmdir()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
