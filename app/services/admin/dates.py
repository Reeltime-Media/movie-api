from datetime import date

from fastapi import HTTPException


def parse_filter_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be YYYY-MM-DD",
        ) from exc
