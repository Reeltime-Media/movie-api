from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(
            settings.effective_database_url,
            debug=settings.debug,
            ssl_root_cert=settings.database_ssl_root_cert or None,
        ),
    )


@lru_cache(maxsize=1)
def get_async_session_maker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


class Base(DeclarativeBase):
    pass
