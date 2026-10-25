from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import deps
from ..utils.media import photo_file

router = APIRouter(
    prefix="/media",
    tags=["Media"],
    dependencies=[Depends(deps.require_user)],
)


@router.get("/photos/{scope}/{filename}")
def get_photo(scope: str, filename: str):
    path = photo_file(filename, scope)
    if path is None:
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    return FileResponse(
        path,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
