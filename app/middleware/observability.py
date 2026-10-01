from __future__ import annotations

import json
import logging
import time

from fastapi import Request

logger = logging.getLogger("app.http")


async def observability_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    payload = {
        "event": "http_request",
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "request_id": getattr(request.state, "request_id", ""),
    }
    line = json.dumps(payload, separators=(",", ":"))
    if response.status_code >= 500:
        logger.error(line)
    elif response.status_code >= 400:
        logger.warning(line)
    else:
        logger.info(line)
    response.headers["X-Response-Time-Ms"] = str(duration_ms)
    return response
