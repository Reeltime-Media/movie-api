import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.free_today_item import FreeTodayItem
from app.schemas.free_today import (
    FreeTodayItemCreate,
    FreeTodayItemRead,
    FreeTodayItemUpdate,
)
from app.services.free_today import enrich_admin_free_today, validate_free_today_add

router = APIRouter()


@router.get("/free-today", response_model=list[FreeTodayItemRead])
async def list_admin_free_today(db: DBSession, _: AdminUser):
    result = await db.execute(
        select(FreeTodayItem).order_by(
            FreeTodayItem.sort_order.asc(),
            FreeTodayItem.created_at.desc(),
        )
    )
    items = list(result.scalars().all())
    return await enrich_admin_free_today(db, items)


@router.post("/free-today", response_model=FreeTodayItemRead, status_code=201)
async def create_admin_free_today(
    data: FreeTodayItemCreate,
    db: DBSession,
    _: AdminUser,
):
    try:
        await validate_free_today_add(db, data.content_id)
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise NotFoundError(message) from exc
        raise ConflictError(message) from exc

    item = FreeTodayItem(**data.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    enriched = await enrich_admin_free_today(db, [item])
    return enriched[0]


@router.patch("/free-today/{item_id}", response_model=FreeTodayItemRead)
async def update_admin_free_today(
    item_id: uuid.UUID,
    data: FreeTodayItemUpdate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(FreeTodayItem).where(FreeTodayItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Free today item not found")

    item.sort_order = data.sort_order
    await db.commit()
    await db.refresh(item)
    enriched = await enrich_admin_free_today(db, [item])
    return enriched[0]


@router.delete("/free-today/{item_id}", status_code=204)
async def delete_admin_free_today(
    item_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(FreeTodayItem).where(FreeTodayItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Free today item not found")
    await db.delete(item)
    await db.commit()
