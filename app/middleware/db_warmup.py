import logging

from fastapi import Request

from app.db_connect import DatabaseWarmup

logger = logging.getLogger(__name__)


def build_database_warmup() -> DatabaseWarmup:
    from app.database import engine
    from app.db_connect import verify_database_connection

    async def ping() -> None:
        await verify_database_connection(engine, attempts=2, base_delay_seconds=1.0)

    return DatabaseWarmup(ping)


db_warmup = build_database_warmup()


async def database_warmup_middleware(request: Request, call_next):
    """
    After Supabase wakes from pause (or a failed startup ping), retry once per request
    instead of failing every catalog query until restart.
    """
    if not getattr(request.app.state, "db_ready", False):
        if await db_warmup.try_connect():
            request.app.state.db_ready = True
            logger.info("Database connection restored")
    return await call_next(request)
