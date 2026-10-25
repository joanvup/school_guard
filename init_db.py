import sys

from sqlalchemy import inspect

from app.auth import get_password_hash
from app.config import settings
from app.database import SessionLocal, engine
from app.models import Door, User, UserRole


def create_default_door():
    db = SessionLocal()
    try:
        if not db.query(Door).first():
            db.add(
                Door(
                    name="Puerta Principal",
                    description="Puerta creada durante la instalación",
                )
            )
            db.commit()
            print("Puerta 'Puerta Principal' creada.")
    finally:
        db.close()


def create_admin():
    if not inspect(engine).has_table("users"):
        print(
            "La base de datos no tiene el esquema. Ejecute 'alembic upgrade head' antes de inicializar.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    password = settings.bootstrap_admin_password
    if not password:
        print(
            "BOOTSTRAP_ADMIN_PASSWORD no está definida. No se creó el administrador.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if len(password) < 12:
        print(
            "BOOTSTRAP_ADMIN_PASSWORD debe tener al menos 12 caracteres.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    db = SessionLocal()
    try:
        existing_user = db.query(User).filter(User.username == "admin").first()
        if existing_user:
            print("El usuario 'admin' ya existe; no se modificó su contraseña.")
            return

        db.add(
            User(
                username="admin",
                full_name="Administrador Principal",
                hashed_password=get_password_hash(password),
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        db.commit()
        print("Usuario 'admin' creado con éxito.")
    finally:
        db.close()


if __name__ == "__main__":
    create_admin()
    create_default_door()
