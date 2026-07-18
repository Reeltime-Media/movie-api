import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db_connect import database_connection_label, validate_database_url, verify_database_connection

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    from app.database import engine

    settings = get_settings()
    db_url = settings.effective_database_url
    app.state.db_ready = False
    for warning in validate_database_url(
        db_url,
        pooler_configured=bool(settings.pooler_database_url),
    ):
        logger.warning("Database config: %s", warning)

    try:
        await verify_database_connection(engine)
        app.state.db_ready = True
        logger.info("Database connected (%s)", database_connection_label(db_url))
    except Exception:
        logger.exception(
            "Database connection failed at startup (%s). "
            "Check POOLER_DATABASE_URL (session mode, port 5432) and network access.",
            database_connection_label(db_url),
        )

    yield

    from app.services.bakong import close_http_client as close_bakong_http_client
    from app.services.email import close_http_client as close_email_http_client
    from app.services.payment import close_http_client as close_payment_http_client
    from app.services.storage import reset_client as reset_storage_client
    from app.services.transcode_client import close_http_client as close_transcode_http_client

    await close_payment_http_client()
    await close_bakong_http_client()
    await close_transcode_http_client()
    await close_email_http_client()
    reset_storage_client()
    await engine.dispose()
