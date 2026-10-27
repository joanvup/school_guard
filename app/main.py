from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import deps
from .config import settings
from .csrf import csrf_cookie_middleware, verify_csrf
from .observability import (
    configure_logging,
    install_exception_handlers,
    request_id_middleware,
)
from .routers import (
    auth,
    cards,
    dashboard,
    doors,
    employees,
    health,
    lunch,
    media,
    pwa,
    reports,
    scan,
    students,
    users,
)
from .security import security_headers_middleware

configure_logging()

docs_enabled = not settings.is_production
app = FastAPI(
    title="School Guard",
    dependencies=[Depends(verify_csrf)],
    docs_url="/docs" if docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if docs_enabled else None,
)

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
app.middleware("http")(security_headers_middleware)
# Debe registrarse al final para quedar como el middleware más externo.
app.middleware("http")(request_id_middleware)
install_exception_handlers(app)

app.include_router(health.router)
app.include_router(pwa.router)
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
