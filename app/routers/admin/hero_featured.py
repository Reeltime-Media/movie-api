import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.hero_featured_item import HeroFeaturedItem
from app.schemas.hero_featured import (
    HeroFeaturedItemCreate,
    HeroFeaturedItemRead,
    HeroFeaturedItemUpdate,
    HeroUploadStart,
    HeroUploadStartRead,
)
from app.services import r2_keys, storage
from app.services.hero_featured import enrich_admin_hero_items, validate_hero_content

router = APIRouter()


@router.get("/hero-featured", response_model=list[HeroFeaturedItemRead])
async def list_admin_hero_featured(db: DBSession, _: AdminUser):
    try:
        result = await db.execute(
            select(HeroFeaturedItem).order_by(
                HeroFeaturedItem.sort_order.asc(),
                HeroFeaturedItem.created_at.desc(),
            )
        )
        items = list(result.scalars().all())
        return await enrich_admin_hero_items(db, items)
    except Exception as exc:
        message = str(exc).lower()
        if "hero_featured_items" in message or "does not exist" in message or "undefinedtable" in message:
            raise HTTPException(
                status_code=503,
                detail=(
                    "hero_featured_items table is missing. "
                    "Run: cd movie-api && alembic upgrade head (or restart the api container)"
                ),
            ) from exc
        raise HTTPException(status_code=500, detail="Could not load hero featured items") from exc


@router.post("/hero-featured", response_model=HeroFeaturedItemRead, status_code=201)
async def create_admin_hero_featured(
    data: HeroFeaturedItemCreate,
    db: DBSession,
    _: AdminUser,
):
    try:
        await validate_hero_content(
            db,
            content_type=data.content_type,
            content_id=data.content_id,
            title=data.title,
        )
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    item = HeroFeaturedItem(**data.model_dump())
    db.add(item)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        message = str(exc).lower()
        if "unique" in message or "duplicate" in message:
            raise ConflictError("This title is already featured for this placement") from exc
        raise
    await db.refresh(item)
    enriched = await enrich_admin_hero_items(db, [item])
    return enriched[0]


@router.patch("/hero-featured/{item_id}", response_model=HeroFeaturedItemRead)
async def update_admin_hero_featured(
    item_id: uuid.UUID,
    data: HeroFeaturedItemUpdate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(HeroFeaturedItem).where(HeroFeaturedItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Hero featured item not found")

    updates = data.model_dump(exclude_unset=True)
    content_type = updates.get("content_type", item.content_type)
    content_id = updates.get("content_id", item.content_id)
    title = updates.get("title", item.title)
    if content_type == "custom":
        # Switching to custom drops any catalog reference.
        content_id = None
        updates["content_id"] = None
    if "content_type" in updates or "content_id" in updates or "title" in updates:
        try:
            await validate_hero_content(
                db,
                content_type=content_type,
                content_id=content_id,
                title=title,
            )
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc

    for field, value in updates.items():
        setattr(item, field, value)

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        message = str(exc).lower()
        if "unique" in message or "duplicate" in message:
            raise ConflictError("This title is already featured for this placement") from exc
        raise
    await db.refresh(item)
    enriched = await enrich_admin_hero_items(db, [item])
    return enriched[0]


@router.delete("/hero-featured/{item_id}", status_code=204)
async def delete_admin_hero_featured(
    item_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(HeroFeaturedItem).where(HeroFeaturedItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Hero featured item not found")
    await db.delete(item)
    await db.commit()


@router.post("/hero-featured/uploads/start", response_model=HeroUploadStartRead)
async def start_admin_hero_upload(data: HeroUploadStart, _: AdminUser):
    media_id = uuid.uuid4()
    if data.kind == "banner":
        key = r2_keys.hero_banner_key(media_id, data.content_type)
    else:
        key = r2_keys.hero_video_key(media_id, data.content_type)
    upload_url = storage.generate_presigned_upload_url(key, data.content_type)
    return HeroUploadStartRead(key=key, upload_url=upload_url)
