import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.routers import admin, auth, comments, movies, payment_test, payments, purchases, series, subscriptions, users, watch_progress, webhooks

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Restrict allow_origins to your frontend domain(s) in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(series.router)
app.include_router(movies.router)
app.include_router(payments.router)
app.include_router(payment_test.router)
app.include_router(purchases.router)
app.include_router(subscriptions.router)
app.include_router(watch_progress.router)
app.include_router(comments.router)
app.include_router(webhooks.router)
app.include_router(admin.router)


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception("Database error")
    detail = "Database error. Please try again."
    message = str(exc).lower()
    if "subscription_plans" in message or "does not exist" in message or "undefinedtable" in message:
        detail = (
            "Database schema is missing subscription_plans. "
            "Run: cd movie-api && alembic upgrade head"
        )
    return JSONResponse(status_code=500, content={"detail": detail})


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
