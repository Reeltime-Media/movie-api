from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs

settings = get_settings()

engine = create_async_engine(
    settings.effective_database_url,
    **sqlalchemy_engine_kwargs(
        settings.effective_database_url,
        debug=settings.debug,
        ssl_root_cert=settings.database_ssl_root_cert or None,
    ),
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass
