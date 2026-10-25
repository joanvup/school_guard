from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from ..config import settings

LOCAL_TZ = ZoneInfo(settings.timezone)


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def today_local() -> date:
    return now_local().date()


def parse_date(value: str | None) -> date:
    if not value:
        return today_local()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Fecha inválida; use el formato AAAA-MM-DD",
        )


def day_bounds(
    date_start: str | None, date_end: str | None
) -> tuple[datetime, datetime, date, date]:
    start_date = parse_date(date_start)
    end_date = parse_date(date_end)
    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La fecha final no puede ser anterior a la inicial",
        )
    return (
        datetime.combine(start_date, time.min),
        datetime.combine(end_date, time.max),
        start_date,
        end_date,
    )
