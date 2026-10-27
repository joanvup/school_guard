import os
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

from fastapi.responses import FileResponse
from openpyxl import Workbook
from starlette.background import BackgroundTask

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
MAX_CELL_LENGTH = 32767


def safe_cell(value):
    if isinstance(value, str):
        if value.startswith(FORMULA_PREFIXES):
            value = "'" + value
        return value[:MAX_CELL_LENGTH]
    return value


def _remove_file(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def build_xlsx(
    *,
    filename: str,
    sheet_name: str,
    headers: Sequence[str],
    rows: Iterable[Sequence],
) -> FileResponse:
    descriptor, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(descriptor)

    try:
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet(title=sheet_name)
        sheet.append([safe_cell(header) for header in headers])
        for row in rows:
            sheet.append([safe_cell(value) for value in row])
        workbook.save(path)
    except Exception:
        _remove_file(path)
        raise

    return FileResponse(
        path,
        filename=filename,
        media_type=XLSX_MEDIA_TYPE,
        background=BackgroundTask(_remove_file, path),
    )
