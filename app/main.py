from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import deps
from .csrf import csrf_cookie_middleware, verify_csrf
from .routers import (
    auth,
    cards,
    dashboard,
    doors,
    employees,
    lunch,
    media,
    reports,
    scan,
    students,
    users,
)

app = FastAPI(title="School Guard", dependencies=[Depends(verify_csrf)])

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def block_legacy_photo_paths(request: Request, call_next):
    if request.url.path.startswith("/static/photos"):
        return Response(status_code=404)
    return await call_next(request)


# Middleware para inyectar el usuario en cada request
@app.middleware("http")
async def add_user_to_request(request: Request, call_next):
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        user = deps.get_current_user(request, db)
        request.state.user = user
    finally:
        db.close()

    return await call_next(request)


app.middleware("http")(csrf_cookie_middleware)

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
app.include_router(media.router)
