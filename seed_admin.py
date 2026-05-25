"""
Seed an admin user (local/bootstrap only).

    ADMIN_SEED_EMAIL=you@example.com ADMIN_SEED_PASSWORD='strong-password' python seed_admin.py

Never use default passwords in production.
"""

import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.security import hash_password
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.user import User

settings = get_settings()

ADMIN_EMAIL = os.environ.get("ADMIN_SEED_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_SEED_PASSWORD", "")
ADMIN_NAME = os.environ.get("ADMIN_SEED_NAME", "Admin").strip() or "Admin"


async def seed():
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        print(
            "Set ADMIN_SEED_EMAIL and ADMIN_SEED_PASSWORD environment variables.",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(ADMIN_PASSWORD) < 8:
        print("ADMIN_SEED_PASSWORD must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)

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
