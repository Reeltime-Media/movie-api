from fastapi import Request
from fastapi.responses import JSONResponse

from app.db_connect import transient_db_detail, verify_database_connection


async def liveness() -> dict[str, str]:
    """Process is up; does not ping the database (safe for orchestrator liveness)."""
    return {"status": "ok"}


async def readiness(request: Request):
    from app.database import engine

    try:
        await verify_database_connection(engine, attempts=2, base_delay_seconds=1.0)
        request.app.state.db_ready = True
        return {"status": "ok", "database": "connected"}
    except Exception:
        request.app.state.db_ready = False
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "database": "unavailable",
                "detail": transient_db_detail(),
            },
        )
