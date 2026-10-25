import enum
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class UserRole(str, enum.Enum):
    ADMIN = "administrador"
    OPERATOR = "operador"  # Operador de Salidas (Portería)
    LUNCH_OP = "operador_almuerzo"  # Comedor


class LunchType(str, enum.Enum):
    NORMAL = "Normal"
    ESPECIAL = "Especial"
    NONE = "Ninguno"


def new_public_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    full_name = Column(String(100))
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.OPERATOR)
    is_active = Column(Boolean, default=True, nullable=False, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    failed_login_count = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    must_change_password = Column(Boolean, nullable=False, default=False, server_default="0")
    token_version = Column(Integer, nullable=False, default=0, server_default="0")


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String(20), unique=True, index=True, nullable=False)  # Ej: Carnet 2023001
    full_name = Column(String(100), nullable=False)
    course = Column(String(20), nullable=False)  # Ej: 10A, 11B
    is_authorized = Column(Boolean, default=False)  # ¿Puede salir?
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    photo_path = Column(String(255), nullable=True)  # Ruta de la foto
    # Control Almuerzos
    rfid_code = Column(String(50), unique=True, index=True, nullable=True)
    has_lunch = Column(Boolean, default=False)  # ¿Tiene almuerzo contratado?
    lunch_type = Column(String(20), default="Ninguno")

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    doc_id = Column(String(20), unique=True, index=True, nullable=False)  # Cédula
    full_name = Column(String(100), nullable=False)
    position = Column(String(50), nullable=True)  # Cargo
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    photo_path = Column(String(255), nullable=True)

    # Control Almuerzos
    rfid_code = Column(String(50), unique=True, index=True, nullable=True)
    has_lunch = Column(Boolean, default=False)
    lunch_type = Column(String(20), default="Normal")

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Door(Base):
    __tablename__ = "doors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)  # Ej: "Puerta Principal"
    description = Column(String(100), nullable=True)  # Ej: "Salida calle 100"
    is_active = Column(Boolean, default=True)


class ExitLog(Base):
    __tablename__ = "exit_logs"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    door_id = Column(Integer, ForeignKey("doors.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)

    # Snapshots para que el histórico no cambie si se edita o desactiva la entidad
    student_name = Column(String(100), nullable=True)
    course = Column(String(20), nullable=True)
    door_name = Column(String(50), nullable=True)
    authorized_at_scan = Column(Boolean, nullable=True)

    __table_args__ = (
        Index("ix_exit_logs_student_timestamp", "student_id", "timestamp"),
        Index("ix_exit_logs_timestamp", "timestamp"),
    )

    # Relaciones
    student = relationship("Student", backref="exits")
    operator = relationship("User")
    door = relationship("Door")


class LunchLog(Base):
    __tablename__ = "lunch_logs"

    id = Column(Integer, primary_key=True, index=True)
    service_date = Column(Date, nullable=False)
    public_id = Column(String(36), nullable=False, unique=True, index=True, default=new_public_id)

    # Puede ser estudiante O empleado (uno de los dos será null)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)

    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)

    # Guardamos qué tipo se entregó (por histórico, si luego cambia su plan)
    delivered_type = Column(String(20), nullable=False)
    identification_method = Column(String(10), nullable=True)

    printed_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_printed_at = Column(DateTime, nullable=True)

    # Snapshots de la persona al momento de la entrega
    person_name = Column(String(100), nullable=True)
    person_extra = Column(String(50), nullable=True)

    __table_args__ = (
        Index(
            "uq_lunch_student_day",
            "student_id",
            "service_date",
            unique=True,
        ),
        Index(
            "uq_lunch_employee_day",
            "employee_id",
            "service_date",
            unique=True,
        ),
        Index("ix_lunch_logs_service_date", "service_date"),
        Index("ix_lunch_logs_timestamp", "timestamp"),
    )

    student = relationship("Student")
    employee = relationship("Employee")
    operator = relationship("User")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(String(50), nullable=True)
    ip = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    details = Column(JSON, nullable=True)
    request_id = Column(String(36), nullable=True)

    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor", "actor_id"),
    )


class ScanAttempt(Base):
    __tablename__ = "scan_attempts"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    module = Column(String(10), nullable=False)  # exit | lunch
    method = Column(String(10), nullable=False)  # qr | rfid | manual
    result = Column(String(20), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="SET NULL"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    door_id = Column(Integer, ForeignKey("doors.id", ondelete="SET NULL"), nullable=True)
    code_hash = Column(String(64), nullable=True)  # SHA-256, nunca el crudo
    reason = Column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_scan_attempts_created_at", "created_at"),
        Index("ix_scan_attempts_module_created", "module", "created_at"),
        Index("ix_scan_attempts_student", "student_id"),
        Index("ix_scan_attempts_employee", "employee_id"),
    )
