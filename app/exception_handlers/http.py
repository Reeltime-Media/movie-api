from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def _request_id(request: Request | None) -> str:
    if request is None:
        return ""
    rid = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID")
    return rid or ""


def error_response(
    request: Request | None,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": _request_id(request),
        "details": details,
    }
    return JSONResponse(status_code=status_code, content=payload)


def _default_message(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, str):
        message = detail
        details = None
    else:
        message = _default_message(exc.status_code)
        details = detail
    return error_response(
        request,
        status_code=exc.status_code,
        code=f"http_{exc.status_code}",
        message=message,
        details=details,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return error_response(
        request,
        status_code=422,
        code="validation_error",
        message="Invalid request parameters",
        details=exc.errors(),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error")
    return error_response(
        request,
        status_code=500,
        code="internal_error",
        message="Internal server error",
    )
