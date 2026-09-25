import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.promotion_banner import PromotionBanner
from app.schemas.promotion_banner import (
    PromotionBannerCreate,
    PromotionBannerImageStart,
    PromotionBannerImageStartRead,
    PromotionBannerRead,
    PromotionBannerUpdate,
)
from app.services import r2_keys, storage
from app.services.image_process import optimize_r2_image

router = APIRouter()


@router.get("/promotion-banners", response_model=list[PromotionBannerRead])
async def list_admin_promotion_banners(db: DBSession, _: AdminUser):
    try:
        result = await db.execute(
            select(PromotionBanner).order_by(
                PromotionBanner.sort_order.asc(),
                PromotionBanner.created_at.desc(),
            )
        )
        return list(result.scalars().all())
    except Exception as exc:
        message = str(exc).lower()
        if "promotion_banners" in message or "does not exist" in message or "undefinedtable" in message:
            raise HTTPException(
                status_code=503,
                detail=(
                    "promotion_banners table is missing. "
                    "Run: cd movie-api && alembic upgrade head (or restart the api container)"
                ),
            ) from exc
        raise HTTPException(status_code=500, detail="Could not load promotion banners") from exc


@router.post("/promotion-banners", response_model=PromotionBannerRead, status_code=201)
async def create_admin_promotion_banner(
    data: PromotionBannerCreate,
    db: DBSession,
    _: AdminUser,
):
    banner = PromotionBanner(**data.model_dump())
    db.add(banner)
    await db.commit()
    await db.refresh(banner)
    return banner


@router.patch("/promotion-banners/{banner_id}", response_model=PromotionBannerRead)
async def update_admin_promotion_banner(
    banner_id: uuid.UUID,
    data: PromotionBannerUpdate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(PromotionBanner).where(PromotionBanner.id == banner_id)
    )
    banner = result.scalar_one_or_none()
    if not banner:
        raise NotFoundError("Promotion banner not found")

    updates = data.model_dump(exclude_unset=True)
    if updates.get("image_key"):
        updates["image_key"] = await optimize_r2_image(updates["image_key"], kind="banner")
    for field, value in updates.items():
        setattr(banner, field, value)

    await db.commit()
    await db.refresh(banner)
    return banner


@router.delete("/promotion-banners/{banner_id}", status_code=204)
async def delete_admin_promotion_banner(
    banner_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(PromotionBanner).where(PromotionBanner.id == banner_id)
    )
    banner = result.scalar_one_or_none()
    if not banner:
        raise NotFoundError("Promotion banner not found")
    await db.delete(banner)
    await db.commit()


@router.post(
    "/promotion-banners/{banner_id}/image/start",
    response_model=PromotionBannerImageStartRead,
)
async def start_admin_promotion_banner_image_upload(
    banner_id: uuid.UUID,
    data: PromotionBannerImageStart,
    _: AdminUser,
    db: DBSession,
):
    result = await db.execute(
        select(PromotionBanner).where(PromotionBanner.id == banner_id)
    )
    banner = result.scalar_one_or_none()
    if not banner:
        raise NotFoundError("Promotion banner not found")

    image_key = r2_keys.promotion_banner_image_key(banner_id, data.content_type)
    upload_url = storage.generate_presigned_upload_url(image_key, data.content_type)
    return PromotionBannerImageStartRead(image_key=image_key, upload_url=upload_url)
