import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _run(command: list[str], db_path: Path, password: str | None):
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    if password is not None:
        env["BOOTSTRAP_ADMIN_PASSWORD"] = password
    return subprocess.run(
        command,
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _alembic(db_path: Path, *args: str):
    return _run([sys.executable, "-m", "alembic", *args], db_path, None)


def test_bootstrap_requires_schema_and_password(tmp_path):
    db_path = tmp_path / "bootstrap.db"

    no_schema = _run([sys.executable, "init_db.py"], db_path, "StrongPassword123!")
    assert no_schema.returncode == 1
    assert "alembic upgrade head" in no_schema.stderr

    upgrade = _alembic(db_path, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    no_password = _run([sys.executable, "init_db.py"], db_path, "")
    assert no_password.returncode == 1
    assert "BOOTSTRAP_ADMIN_PASSWORD no est" in no_password.stderr

    short_password = _run([sys.executable, "init_db.py"], db_path, "corta")
    assert short_password.returncode == 1
    assert "al menos 12" in short_password.stderr

    created = _run([sys.executable, "init_db.py"], db_path, "StrongPassword123!")
    assert created.returncode == 0, created.stderr

    repeated = _run([sys.executable, "init_db.py"], db_path, "StrongPassword123!")
    assert repeated.returncode == 0
    assert "ya existe" in repeated.stdout

    connection = sqlite3.connect(db_path)
    try:
        role = connection.execute("SELECT role FROM users WHERE username = 'admin'").fetchone()[0]
        assert role == "ADMIN"
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM doors").fetchone()[0] == 1
    finally:
        connection.close()
