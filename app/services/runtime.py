from fastapi import HTTPException

from app.models.content import Content


def format_runtime_display(minutes: int) -> str:
    hours, rem = divmod(minutes, 60)
    if hours and rem:
        return f"{hours}h {rem}m"
    if hours:
        return f"{hours}h"
    return f"{rem}m"


def apply_runtime_minutes(content: Content, minutes: int | None) -> None:
    if minutes is None:
        return
    if minutes <= 0:
        raise HTTPException(status_code=422, detail="Runtime must be a positive number of minutes")
    content.duration_seconds = minutes * 60
    content.runtime = format_runtime_display(minutes)
