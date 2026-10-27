import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import settings

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,36}$")

logger = logging.getLogger("school_guard.requests")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": current_request_id(),
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # El access log de uvicorn duplica la línea estructurada de este módulo.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def current_request_id() -> str | None:
    return _request_id.get()


def _valid_request_id(value: str | None) -> str | None:
    if value and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return None


def _context(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    return {
        "method": request.method,
        "path": request.url.path,
        "user_id": getattr(user, "id", None),
    }


async def request_id_middleware(request: Request, call_next):
    request_id = _valid_request_id(request.headers.get("x-request-id")) or uuid.uuid4().hex
    token = _request_id.set(request_id)
    request.state.request_id = request_id
    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request.failed",
            extra={
                "context": {
                    **_context(request),
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            },
        )
        raise
    else:
        response.headers.setdefault("X-Request-ID", request_id)
        logger.info(
            "request.completed",
            extra={
                "context": {
                    **_context(request),
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            },
        )
        return response
    finally:
        _request_id.reset(token)


def install_exception_handlers(app: FastAPI) -> None:
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or current_request_id()
        logger.error(
            "unhandled.exception",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={
                "context": {
                    "path": request.url.path,
                    "method": request.method,
                    "request_id": request_id,
                }
            },
        )
        headers = {"X-Request-ID": request_id} if request_id else None
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno", "request_id": request_id},
            headers=headers,
        )

    app.add_exception_handler(Exception, unhandled_exception)
