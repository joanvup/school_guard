import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .. import database

router = APIRouter(tags=["Health"])
logger = logging.getLogger("school_guard.health")


@router.get("/healthz")
def healthz():
    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logger.exception("healthz.database_unavailable")
        return JSONResponse(status_code=503, content={"status": "degraded"})
    return {"status": "ok"}
