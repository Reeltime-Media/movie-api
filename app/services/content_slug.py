import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Content


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


async def unique_content_slug(base: str, db: AsyncSession) -> str:
    slug = slugify(base)
    existing = await db.execute(select(Content).where(Content.slug == slug))
    if not existing.scalar_one_or_none():
        return slug
    return f"{slug}-{uuid.uuid4().hex[:6]}"
