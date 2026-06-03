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
from app.rate_limit import limiter
from app.routers import (
    admin,
    auth,
    comments,
    hero_featured,
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
    from app.db_connect import (
        database_connection_label,
        validate_database_url,
        verify_database_connection,
    )

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

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


def _is_db_unreachable(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, (OperationalError, DBAPIError)):
        message = str(exc).lower()
        return "timeout" in message or "cancelled" in message or "connection" in message
    cause = getattr(exc, "__cause__", None)
    return bool(cause and _is_db_unreachable(cause))


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
    if _is_db_unreachable(exc):
        logger.error("Database unreachable: %s", exc.__class__.__name__)
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Database is unreachable. Verify POOLER_DATABASE_URL "
                    "(Supabase session pooler, port 5432) and that the project is active."
                ),
            },
        )

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
    if getattr(request.app.state, "db_ready", False):
        return {"status": "ok", "database": "connected"}
    return JSONResponse(
        status_code=503,
        content={
            "status": "degraded",
            "database": "unavailable",
            "detail": "Set POOLER_DATABASE_URL to Supabase session pooler (port 5432).",
        },
    )
