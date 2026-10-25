"""Normaliza photo_path al nombre base del archivo.

Revision ID: 0003_photo_paths
Revises: 0002_security_and_audit
Create Date: 2026-10-25
"""

from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0003_photo_paths"
down_revision = "0002_security_and_audit"
branch_labels = None
depends_on = None


def _normalize_stored_path(value: str | None) -> str | None:
    if not value:
        return None
    name = Path(value.replace("\\", "/")).name.strip()
    return name or None


def _normalize_table(bind, table: str) -> None:
    rows = bind.execute(sa.text(f"SELECT id, photo_path FROM {table}")).fetchall()
    for row in rows:
        normalized = _normalize_stored_path(row.photo_path)
        if normalized != row.photo_path:
            bind.execute(
                sa.text(f"UPDATE {table} SET photo_path = :path WHERE id = :id"),
                {"path": normalized, "id": row.id},
            )


def upgrade() -> None:
    bind = op.get_bind()
    _normalize_table(bind, "students")
    _normalize_table(bind, "employees")


def downgrade() -> None:
    # Solo se perdieron prefijos de ruta; no es posible reconstruirlos.
    pass
