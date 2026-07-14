import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db_connect import verify_database_connection
from app.exception_handlers.database import (
    sqlalchemy_error_handler,
    timeout_error_handler,
)
from app.lifespan import app_lifespan
from app.middleware.db_warmup import database_warmup_middleware, db_warmup
from app.middleware.security import security_headers_middleware
from app.rate_limit import limiter
from app.routers import (
    admin,
    auth,
    comments,
    favorites,
    genres,
    health,
    free_today,
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


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=app_lifespan,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_exception_handler(TimeoutError, timeout_error_handler)
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
    app.add_middleware(SlowAPIMiddleware)

    cors_kwargs: dict = {
        "allow_origins": settings.cors_origin_list,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type", "Accept"],
    }
    if settings.cors_origin_regex:
        cors_kwargs["allow_origin_regex"] = settings.cors_origin_regex
    app.add_middleware(CORSMiddleware, **cors_kwargs)

    app.middleware("http")(security_headers_middleware)
    app.middleware("http")(database_warmup_middleware)

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(series.router)
    app.include_router(movies.router)
    app.include_router(payments.router)
    app.include_router(promotions.router)
    app.include_router(hero_featured.router)
    app.include_router(free_today.router)
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

    register_health_routes(app)
    return app


def register_health_routes(app: FastAPI) -> None:
    app.add_api_route(
        "/health/live",
        health.liveness,
        methods=["GET"],
        tags=["health"],
        response_model=None,
    )
    app.add_api_route(
        "/health",
        health.readiness,
        methods=["GET"],
        tags=["health"],
        response_model=None,
    )


app = create_app()
