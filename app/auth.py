from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
import os
import hmac
import hashlib

# Configuración
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"))

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Leer el secreto nuevo
QR_SECRET_KEY = os.getenv("QR_SECRET_KEY", "secreto_por_defecto_inseguro")

def sign_qr_content(student_id: str) -> str:
    """
    Genera un string firmado: ID.FIRMA
    Ejemplo: 2023001.f8a9...
    """
    # Convertir a bytes
    key = bytes(QR_SECRET_KEY, 'utf-8')
    msg = bytes(student_id, 'utf-8')
    
    # Crear firma HMAC SHA256
    signature = hmac.new(key, msg, hashlib.sha256).hexdigest()
    
    # Retornar formato combinado (usamos punto como separador)
    return f"{student_id}.{signature[:16]}" # Usamos los primeros 16 caracteres del hash para que el QR no sea gigante

def verify_qr_content(qr_content: str) -> str:
    """
    Verifica la firma. Si es válida, retorna el student_id limpio.
    Si es inválida, retorna None.
    """
    try:
        if "." not in qr_content:
            return None # Formato inválido (probablemente un QR viejo o falso)
            
        student_id, received_sig = qr_content.split(".", 1)
        
        # Recalcular firma real
        key = bytes(QR_SECRET_KEY, 'utf-8')
        msg = bytes(student_id, 'utf-8')
        expected_full_sig = hmac.new(key, msg, hashlib.sha256).hexdigest()
        expected_sig = expected_full_sig[:16]
        
        # Comparación segura contra ataques de tiempo
        if hmac.compare_digest(expected_sig, received_sig):
            return student_id
        else:
            return None
    except Exception:
        return None