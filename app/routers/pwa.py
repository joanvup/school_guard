from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["PWA"])

SW_PATH = Path(__file__).resolve().parent.parent / "static" / "sw.js"


@router.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(
        SW_PATH,
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        },
    )
