import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.coming_soon_item import ComingSoonItem
from app.schemas.coming_soon import (
    ComingSoonItemCreate,
    ComingSoonItemRead,
    ComingSoonItemUpdate,
)
from app.services.coming_soon import enrich_admin_coming_soon, validate_coming_soon_add

router = APIRouter()


@router.get("/coming-soon", response_model=list[ComingSoonItemRead])
async def list_admin_coming_soon(db: DBSession, _: AdminUser):
    result = await db.execute(
        select(ComingSoonItem).order_by(
            ComingSoonItem.sort_order.asc(),
            ComingSoonItem.created_at.desc(),
        )
    )
    items = list(result.scalars().all())
    return await enrich_admin_coming_soon(db, items)


@router.post("/coming-soon", response_model=ComingSoonItemRead, status_code=201)
async def create_admin_coming_soon(
    data: ComingSoonItemCreate,
    db: DBSession,
    _: AdminUser,
):
    try:
        await validate_coming_soon_add(db, data.content_id)
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise NotFoundError(message) from exc
        raise ConflictError(message) from exc

    item = ComingSoonItem(**data.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    enriched = await enrich_admin_coming_soon(db, [item])
    return enriched[0]


@router.patch("/coming-soon/{item_id}", response_model=ComingSoonItemRead)
async def update_admin_coming_soon(
    item_id: uuid.UUID,
    data: ComingSoonItemUpdate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(ComingSoonItem).where(ComingSoonItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Coming Soon item not found")

    item.sort_order = data.sort_order
    await db.commit()
    await db.refresh(item)
    enriched = await enrich_admin_coming_soon(db, [item])
    return enriched[0]


@router.delete("/coming-soon/{item_id}", status_code=204)
async def delete_admin_coming_soon(
    item_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(ComingSoonItem).where(ComingSoonItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Coming Soon item not found")
    await db.delete(item)
    await db.commit()
