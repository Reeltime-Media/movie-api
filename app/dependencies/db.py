from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session_maker


async def get_db():
    async_session_maker = get_async_session_maker()
    async with async_session_maker() as session:
        yield session


DBSession = Annotated[AsyncSession, Depends(get_db)]
