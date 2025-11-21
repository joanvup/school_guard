from app.database import SessionLocal, engine
from app.models import Base, User, UserRole
from app.auth import get_password_hash

# Asegurar que las tablas existen
Base.metadata.create_all(bind=engine)

def create_admin():
    db = SessionLocal()
    username = "admin"
    
    # Verificar si ya existe
    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        print(f"El usuario '{username}' ya existe.")
        return

    # Crear admin
    hashed_pw = get_password_hash("admin123") # Contraseña por defecto
    new_user = User(
        username=username,
        full_name="Administrador Principal",
        hashed_password=hashed_pw,
        role=UserRole.ADMIN
    )
    
    db.add(new_user)
    db.commit()
    print(f"Usuario '{username}' creado con éxito (Pass: admin123).")
    db.close()

if __name__ == "__main__":
    create_admin()