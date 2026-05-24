"""
Seed an admin user.
Run from the movie-api directory:

    python seed_admin.py
"""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.security import hash_password
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.user import User

settings = get_settings()

ADMIN_EMAIL = "admin@gmail.com"
ADMIN_PASSWORD = "admin123"
ADMIN_NAME = "Admin"


async def seed():
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(settings.effective_database_url, debug=False),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        result = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        existing = result.scalar_one_or_none()

        if existing:
            print(f"Admin already exists: {ADMIN_EMAIL}")
            await engine.dispose()
            return

        admin = User(
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            full_name=ADMIN_NAME,
            role="admin",
            is_active=True,
        )
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        print(f"Admin created — id: {admin.id}  email: {admin.email}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
