import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.db_connect import exception_from_db_layer, is_transient_db_error, transient_db_detail

logger = logging.getLogger(__name__)


def db_unavailable_response() -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": transient_db_detail()})


async def timeout_error_handler(_request: Request, exc: TimeoutError) -> JSONResponse:
    if exception_from_db_layer(exc):
        logger.error("Database timeout")
        return db_unavailable_response()
    logger.error("Request timeout: %s", exc)
    return JSONResponse(status_code=503, content={"detail": str(exc) or "Request timed out"})


async def sqlalchemy_error_handler(_request: Request, exc) -> JSONResponse:
    from app.config import get_settings

    settings = get_settings()
    if is_transient_db_error(exc):
        logger.error("Database unreachable: %s", exc.__class__.__name__)
        return db_unavailable_response()

    logger.exception("Database error")
    detail = "Database error. Please try again."
    message = str(exc).lower()
    if settings.debug and (
        "subscription_plans" in message
        or "does not exist" in message
        or "undefinedtable" in message
    ):
        detail = (
            "Database schema is missing subscription_plans. "
            "Run: cd movie-api && alembic upgrade head"
        )
    return JSONResponse(status_code=500, content={"detail": detail})
