import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError

from app.config import get_settings
from app.db_connect import is_transient_db_error, transient_db_detail, verify_database_connection
from app.rate_limit import limiter
from app.routers import (
    admin,
    auth,
    comments,
    favorites,
    genres,
    hero_featured,
    library,
    movies,
    payments,
    playback,
    promotions,
    purchases,
    series,
    subscriptions,
    users,
    watch_progress,
    webhooks,
)

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    from app.database import engine
    from app.db_connect import database_connection_label, validate_database_url

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

    from app.services.payment import close_http_client as close_payment_http_client
    from app.services.storage import reset_client as reset_storage_client
    from app.services.transcode_client import close_http_client as close_transcode_http_client

    await close_payment_http_client()
    await close_transcode_http_client()
    reset_storage_client()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=app_lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

_cors_kwargs: dict = {
    "allow_origins": settings.cors_origin_list,
    "allow_credentials": True,
    "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    "allow_headers": ["Authorization", "Content-Type", "Accept"],
}
if settings.cors_origin_regex:
    _cors_kwargs["allow_origin_regex"] = settings.cors_origin_regex
app.add_middleware(CORSMiddleware, **_cors_kwargs)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(series.router)
app.include_router(movies.router)
app.include_router(payments.router)
app.include_router(promotions.router)
app.include_router(hero_featured.router)
app.include_router(playback.router)
app.include_router(purchases.router)
app.include_router(subscriptions.router)
app.include_router(watch_progress.router)
app.include_router(comments.router)
app.include_router(favorites.router)
app.include_router(genres.router)
app.include_router(library.router)
app.include_router(webhooks.router)
app.include_router(admin.router)

if settings.debug:
    from app.routers import payment_test

    app.include_router(payment_test.router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.middleware("http")
async def database_warmup(request: Request, call_next):
    """
    After Supabase wakes from pause (or a failed startup ping), retry once per request
    instead of failing every catalog query until restart.
    """
    if not getattr(request.app.state, "db_ready", False):
        from app.database import engine

        try:
            await verify_database_connection(engine, attempts=2, base_delay_seconds=1.0)
            request.app.state.db_ready = True
            logger.info("Database connection restored")
        except Exception:
            pass
    return await call_next(request)


def _db_unavailable_response() -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": transient_db_detail()})


@app.exception_handler(TimeoutError)
async def timeout_error_handler(_request: Request, _exc: TimeoutError) -> JSONResponse:
    logger.error("Database timeout")
    return _db_unavailable_response()


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
    if is_transient_db_error(exc):
        logger.error("Database unreachable: %s", exc.__class__.__name__)
        return _db_unavailable_response()

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


@app.get("/health", tags=["health"])
async def health(request: Request):
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
