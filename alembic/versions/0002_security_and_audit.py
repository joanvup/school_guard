"""Fase 1: seguridad de login, auditoría e integridad de almuerzos.

Revision ID: 0002_security_and_audit
Revises: 0001_baseline
Create Date: 2026-10-25
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0002_security_and_audit"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _lunch_duplicates(bind, person_column: str):
    return bind.execute(
        sa.text(
            f"""
            SELECT {person_column} AS person_id,
                   DATE(timestamp) AS service_day,
                   COUNT(*) AS total
            FROM lunch_logs
            WHERE {person_column} IS NOT NULL
            GROUP BY {person_column}, DATE(timestamp)
            HAVING COUNT(*) > 1
            ORDER BY service_day, person_id
            """
        )
    ).fetchall()


def _assert_no_lunch_duplicates(bind) -> None:
    rows = _lunch_duplicates(bind, "student_id") + _lunch_duplicates(bind, "employee_id")
    if rows:
        detalle = "; ".join(
            f"persona {row.person_id}: {row.service_day} ({row.total} registros)"
            for row in rows[:20]
        )
        raise RuntimeError(
            "Hay almuerzos duplicados por persona y día. Depure y archive los "
            f"sobrantes antes de migrar. Grupos afectados: {len(rows)}. "
            f"Primeros casos: {detalle}"
        )


def upgrade() -> None:
    bind = op.get_bind()

    # Se comprueba antes de cualquier DDL para no dejar el esquema a medias.
    _assert_no_lunch_duplicates(bind)

    op.execute("UPDATE users SET is_active = 1 WHERE is_active IS NULL")
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "is_active",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        )
        batch.add_column(
            sa.Column(
                "failed_login_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(sa.Column("locked_until", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_login_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column(
                "must_change_password",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "token_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )

    with op.batch_alter_table("students") as batch:
        batch.add_column(
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            )
        )

    with op.batch_alter_table("employees") as batch:
        batch.add_column(
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            )
        )

    with op.batch_alter_table("exit_logs") as batch:
        batch.add_column(sa.Column("student_name", sa.String(length=100)))
        batch.add_column(sa.Column("course", sa.String(length=20)))
        batch.add_column(sa.Column("door_name", sa.String(length=50)))
        batch.add_column(sa.Column("authorized_at_scan", sa.Boolean()))

    op.execute(
        """
        UPDATE exit_logs
        SET student_name = (
                SELECT full_name FROM students
                WHERE students.id = exit_logs.student_id
            ),
            course = (
                SELECT course FROM students
                WHERE students.id = exit_logs.student_id
            ),
            door_name = (
                SELECT name FROM doors
                WHERE doors.id = exit_logs.door_id
            ),
            authorized_at_scan = (
                SELECT is_authorized FROM students
                WHERE students.id = exit_logs.student_id
            )
        """
    )
    op.create_index(
        "ix_exit_logs_student_timestamp",
        "exit_logs",
        ["student_id", "timestamp"],
        unique=False,
    )
    op.create_index("ix_exit_logs_timestamp", "exit_logs", ["timestamp"], unique=False)

    with op.batch_alter_table("lunch_logs") as batch:
        batch.add_column(sa.Column("service_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("public_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("identification_method", sa.String(length=10), nullable=True))
        batch.add_column(
            sa.Column(
                "printed_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(sa.Column("last_printed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("person_name", sa.String(length=100)))
        batch.add_column(sa.Column("person_extra", sa.String(length=50)))

    op.execute(
        """
        UPDATE lunch_logs
        SET service_date = DATE(timestamp),
            person_name = COALESCE(
                (SELECT full_name FROM students
                 WHERE students.id = lunch_logs.student_id),
                (SELECT full_name FROM employees
                 WHERE employees.id = lunch_logs.employee_id)
            ),
            person_extra = COALESCE(
                (SELECT course FROM students
                 WHERE students.id = lunch_logs.student_id),
                (SELECT position FROM employees
                 WHERE employees.id = lunch_logs.employee_id)
            )
        """
    )

    missing_dates = bind.execute(
        sa.text("SELECT COUNT(*) FROM lunch_logs WHERE service_date IS NULL")
    ).scalar()
    if missing_dates:
        raise RuntimeError(
            f"{missing_dates} registros de almuerzo no pudieron obtener service_date; "
            "revise timestamps nulos o inválidos antes de migrar."
        )

    for row_id in (
        bind.execute(sa.text("SELECT id FROM lunch_logs WHERE public_id IS NULL")).scalars().all()
    ):
        bind.execute(
            sa.text("UPDATE lunch_logs SET public_id = :public_id WHERE id = :id"),
            {"public_id": str(uuid.uuid4()), "id": row_id},
        )

    with op.batch_alter_table("lunch_logs") as batch:
        batch.alter_column("service_date", existing_type=sa.Date(), nullable=False)
        batch.alter_column("public_id", existing_type=sa.String(length=36), nullable=False)

    op.create_index("ix_lunch_logs_public_id", "lunch_logs", ["public_id"], unique=True)
    op.create_index(
        "uq_lunch_student_day",
        "lunch_logs",
        ["student_id", "service_date"],
        unique=True,
    )
    op.create_index(
        "uq_lunch_employee_day",
        "lunch_logs",
        ["employee_id", "service_date"],
        unique=True,
    )
    op.create_index("ix_lunch_logs_service_date", "lunch_logs", ["service_date"], unique=False)
    op.create_index("ix_lunch_logs_timestamp", "lunch_logs", ["timestamp"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", sa.String(length=50), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"], unique=False)
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index(
        "ix_audit_logs_entity",
        "audit_logs",
        ["entity_type", "entity_id"],
        unique=False,
    )
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor_id"], unique=False)

    op.create_table(
        "scan_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("module", sa.String(length=10), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=True),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("door_id", sa.Integer(), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["door_id"], ["doors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scan_attempts_id", "scan_attempts", ["id"], unique=False)
    op.create_index(
        "ix_scan_attempts_created_at",
        "scan_attempts",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_scan_attempts_module_created",
        "scan_attempts",
        ["module", "created_at"],
        unique=False,
    )
    op.create_index("ix_scan_attempts_student", "scan_attempts", ["student_id"], unique=False)
    op.create_index("ix_scan_attempts_employee", "scan_attempts", ["employee_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scan_attempts_employee", table_name="scan_attempts")
    op.drop_index("ix_scan_attempts_student", table_name="scan_attempts")
    op.drop_index("ix_scan_attempts_module_created", table_name="scan_attempts")
    op.drop_index("ix_scan_attempts_created_at", table_name="scan_attempts")
    op.drop_index("ix_scan_attempts_id", table_name="scan_attempts")
    op.drop_table("scan_attempts")

    op.drop_index("ix_audit_logs_actor", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_lunch_logs_timestamp", table_name="lunch_logs")
    op.drop_index("ix_lunch_logs_service_date", table_name="lunch_logs")
    op.drop_index("uq_lunch_employee_day", table_name="lunch_logs")
    op.drop_index("uq_lunch_student_day", table_name="lunch_logs")
    op.drop_index("ix_lunch_logs_public_id", table_name="lunch_logs")

    with op.batch_alter_table("lunch_logs") as batch:
        batch.drop_column("person_extra")
        batch.drop_column("person_name")
        batch.drop_column("last_printed_at")
        batch.drop_column("printed_count")
        batch.drop_column("identification_method")
        batch.drop_column("public_id")
        batch.drop_column("service_date")

    op.drop_index("ix_exit_logs_timestamp", table_name="exit_logs")
    op.drop_index("ix_exit_logs_student_timestamp", table_name="exit_logs")

    with op.batch_alter_table("exit_logs") as batch:
        batch.drop_column("authorized_at_scan")
        batch.drop_column("door_name")
        batch.drop_column("course")
        batch.drop_column("student_name")

    with op.batch_alter_table("employees") as batch:
        batch.drop_column("is_active")

    with op.batch_alter_table("students") as batch:
        batch.drop_column("is_active")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("token_version")
        batch.drop_column("must_change_password")
        batch.drop_column("last_login_at")
        batch.drop_column("locked_until")
        batch.drop_column("failed_login_count")
        batch.alter_column("is_active", existing_type=sa.Boolean(), nullable=True)
