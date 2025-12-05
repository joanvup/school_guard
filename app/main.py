from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from .database import engine
from .routers import auth, dashboard, students, cards, scan, doors, reports, users, employees, lunch
from . import models, deps

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="School Guard")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Middleware para inyectar el usuario en cada request
@app.middleware("http")
async def add_user_to_request(request: Request, call_next):
    # Usamos la lógica de deps.get_current_user manualmente aquí
    # para no bloquear rutas públicas, pero tener el usuario si existe.
    from app.database import SessionLocal
    db = SessionLocal()
    user = deps.get_current_user(request, db)
    request.state.user = user
    db.close()
    
    response = await call_next(request)
    return response

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(students.router)
app.include_router(cards.router)
app.include_router(scan.router)
app.include_router(doors.router)
app.include_router(reports.router)
app.include_router(users.router)
app.include_router(employees.router) 
app.include_router(lunch.router)

@app.get("/")
def root(request: Request):
    if request.state.user:
        return RedirectResponse("/dashboard")
    return RedirectResponse("/login") # Asumiendo que auth.router maneja /login o la raiz