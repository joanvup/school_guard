from sqlalchemy import Column, Integer, String, Enum, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base
import enum

class UserRole(str, enum.Enum):
    ADMIN = "administrador"
    OPERATOR = "operador"         # Operador de Salidas (Portería)
    LUNCH_OP = "operador_almuerzo" # Nuevo rol: Comedor

class LunchType(str, enum.Enum):
    NORMAL = "Normal"
    ESPECIAL = "Especial"
    NONE = "Ninguno"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    full_name = Column(String(100))
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.OPERATOR)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String(20), unique=True, index=True, nullable=False) # Ej: Carnet 2023001
    full_name = Column(String(100), nullable=False)
    course = Column(String(20), nullable=False) # Ej: 10A, 11B
    is_authorized = Column(Boolean, default=False) # ¿Puede salir?
    photo_path = Column(String(255), nullable=True) # Ruta de la foto
    # Control Almuerzos (Nuevos campos)
    rfid_code = Column(String(50), unique=True, index=True, nullable=True) # Código del chip NFC/RFID
    has_lunch = Column(Boolean, default=False) # ¿Tiene almuerzo contratado?
    lunch_type = Column(String(20), default="Ninguno")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Employee(Base):
    __tablename__ = "employees"
    
    id = Column(Integer, primary_key=True, index=True)
    doc_id = Column(String(20), unique=True, index=True, nullable=False) # Cédula
    full_name = Column(String(100), nullable=False)
    position = Column(String(50), nullable=True) # Cargo
    photo_path = Column(String(255), nullable=True)
    
    # Control Almuerzos
    rfid_code = Column(String(50), unique=True, index=True, nullable=True)
    has_lunch = Column(Boolean, default=False)
    lunch_type = Column(String(20), default="Normal")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Door(Base):
    __tablename__ = "doors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False) # Ej: "Puerta Principal"
    description = Column(String(100), nullable=True)       # Ej: "Salida calle 100"
    is_active = Column(Boolean, default=True)

class ExitLog(Base):
    __tablename__ = "exit_logs"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    door_id = Column(Integer, ForeignKey("doors.id"), nullable=False) 
    timestamp = Column(DateTime(timezone=True), nullable=False)

    # Relaciones
    student = relationship("Student", backref="exits")
    operator = relationship("User")
    door = relationship("Door")

class LunchLog(Base):
    __tablename__ = "lunch_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Puede ser estudiante O empleado (uno de los dos será null)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    
    # Guardamos qué tipo se entregó (por histórico, si luego cambia su plan)
    delivered_type = Column(String(20), nullable=False)

    student = relationship("Student")
    employee = relationship("Employee")
    operator = relationship("User")