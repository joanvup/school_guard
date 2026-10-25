import os
import shutil
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix="school_guard_tests_"))
DB_PATH = TEST_ROOT / "test.db"
ADMIN_PASSWORD = "TestAdminPass123!"
USER_PASSWORD = "TestUserPass123!"

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-for-school-guard"
os.environ["QR_SECRET_KEY_CURRENT"] = "test-qr-key-current"
os.environ["QR_SECRET_KEY_PREVIOUS"] = "test-qr-key-previous"
os.environ["COOKIE_SECURE"] = "false"
os.environ["LOGIN_MAX_ATTEMPTS"] = "5"
os.environ["LOGIN_LOCKOUT_MINUTES"] = "5"
os.environ["MEDIA_PHOTOS_DIR"] = str(TEST_ROOT / "photos")
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = ADMIN_PASSWORD

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, models  # noqa: E402
from app.database import Base, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def apply_migrations():
    config = Config(str(BASE_DIR / "alembic.ini"))
    command.upgrade(config, "head")
    yield
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


def _create_user(db, username, password, role, is_active=True):
    db.add(
        models.User(
            username=username,
            full_name=username.title(),
            hashed_password=auth.get_password_hash(password),
            role=role,
            is_active=is_active,
        )
    )


@pytest.fixture(autouse=True)
def reset_database(apply_migrations):
    db = SessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()

        _create_user(db, "admin", ADMIN_PASSWORD, models.UserRole.ADMIN)
        _create_user(db, "operator", USER_PASSWORD, models.UserRole.OPERATOR)
        _create_user(db, "lunch", USER_PASSWORD, models.UserRole.LUNCH_OP)
        _create_user(db, "inactive", USER_PASSWORD, models.UserRole.OPERATOR, is_active=False)
        db.add(
            models.Door(
                name="Puerta Principal",
                description="Puerta de pruebas",
                is_active=True,
            )
        )
        db.commit()
    finally:
        db.close()

    auth.login_limiter._attempts.clear()
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
