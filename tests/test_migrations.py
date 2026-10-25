import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _run_alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_migrations_upgrade_check_and_downgrade(tmp_path):
    db_path = tmp_path / "migrations.db"

    upgrade = _run_alembic(db_path, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    check = _run_alembic(db_path, "check")
    assert check.returncode == 0, check.stdout + check.stderr

    downgrade = _run_alembic(db_path, "downgrade", "base")
    assert downgrade.returncode == 0, downgrade.stderr

    upgrade_again = _run_alembic(db_path, "upgrade", "head")
    assert upgrade_again.returncode == 0, upgrade_again.stderr


def test_duplicate_lunches_abort_before_schema_changes(tmp_path):
    db_path = tmp_path / "duplicates.db"

    baseline = _run_alembic(db_path, "upgrade", "0001_baseline")
    assert baseline.returncode == 0, baseline.stderr

    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            INSERT INTO users (id, username, hashed_password, is_active)
            VALUES (1, 'u', 'x', 1);
            INSERT INTO students (id, student_id, full_name, course)
            VALUES (1, 'S1', 'Ana', '10A');
            INSERT INTO doors (id, name, is_active) VALUES (1, 'Principal', 1);
            INSERT INTO lunch_logs (id, student_id, operator_id, timestamp, delivered_type)
            VALUES (1, 1, 1, '2026-10-20 12:00:00', 'Normal');
            INSERT INTO lunch_logs (id, student_id, operator_id, timestamp, delivered_type)
            VALUES (2, 1, 1, '2026-10-20 12:05:00', 'Normal');
            """
        )
        connection.commit()
    finally:
        connection.close()

    result = _run_alembic(db_path, "upgrade", "head")
    assert result.returncode != 0
    output = (result.stdout + result.stderr).lower()
    assert "duplicados" in output

    connection = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info('lunch_logs')")}
    finally:
        connection.close()
    assert "service_date" not in columns
    assert "public_id" not in columns
