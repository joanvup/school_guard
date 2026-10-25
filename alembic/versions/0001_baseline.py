"""Baseline del esquema existente antes de la Fase 1.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-25

Representa las siete tablas que la aplicación creaba con ``create_all`` antes
de introducir Alembic. No modifica datos.
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("full_name", sa.String(length=100), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("ADMIN", "OPERATOR", "LUNCH_OP", name="userrole"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.String(length=20), nullable=False),
        sa.Column("full_name", sa.String(length=100), nullable=False),
        sa.Column("course", sa.String(length=20), nullable=False),
        sa.Column("is_authorized", sa.Boolean(), nullable=True),
        sa.Column("photo_path", sa.String(length=255), nullable=True),
        sa.Column("rfid_code", sa.String(length=50), nullable=True),
        sa.Column("has_lunch", sa.Boolean(), nullable=True),
        sa.Column("lunch_type", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_students_id", "students", ["id"], unique=False)
    op.create_index("ix_students_student_id", "students", ["student_id"], unique=True)
    op.create_index("ix_students_rfid_code", "students", ["rfid_code"], unique=True)

    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("doc_id", sa.String(length=20), nullable=False),
        sa.Column("full_name", sa.String(length=100), nullable=False),
        sa.Column("position", sa.String(length=50), nullable=True),
        sa.Column("photo_path", sa.String(length=255), nullable=True),
        sa.Column("rfid_code", sa.String(length=50), nullable=True),
        sa.Column("has_lunch", sa.Boolean(), nullable=True),
        sa.Column("lunch_type", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_employees_id", "employees", ["id"], unique=False)
    op.create_index("ix_employees_doc_id", "employees", ["doc_id"], unique=True)
    op.create_index("ix_employees_rfid_code", "employees", ["rfid_code"], unique=True)

    op.create_table(
        "doors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_doors_id", "doors", ["id"], unique=False)

    op.create_table(
        "exit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("door_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["door_id"], ["doors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_exit_logs_id", "exit_logs", ["id"], unique=False)

    op.create_table(
        "lunch_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=True),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_type", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lunch_logs_id", "lunch_logs", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_lunch_logs_id", table_name="lunch_logs")
    op.drop_table("lunch_logs")

    op.drop_index("ix_exit_logs_id", table_name="exit_logs")
    op.drop_table("exit_logs")

    op.drop_index("ix_doors_id", table_name="doors")
    op.drop_table("doors")

    op.drop_index("ix_employees_rfid_code", table_name="employees")
    op.drop_index("ix_employees_doc_id", table_name="employees")
    op.drop_index("ix_employees_id", table_name="employees")
    op.drop_table("employees")

    op.drop_index("ix_students_rfid_code", table_name="students")
    op.drop_index("ix_students_student_id", table_name="students")
    op.drop_index("ix_students_id", table_name="students")
    op.drop_table("students")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
