import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.rate_limit import limiter
from app.routers import (
    admin,
    auth,
    comments,
    movies,
    payments,
    purchases,
    series,
    subscriptions,
    users,
    watch_progress,
    webhooks,
)

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(series.router)
app.include_router(movies.router)
app.include_router(payments.router)
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


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
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
async def health():
    return {"status": "ok"}
