"""Public promotion banners for the client storefront."""

from fastapi import APIRouter, Query

from app.dependencies import DBSession
from app.schemas.promotion_banner import PromotionBannerRead
from app.services.promotion_banners import list_active_promotion_banners

router = APIRouter(prefix="/promotion-banners", tags=["promotions"])


@router.get("/", response_model=list[PromotionBannerRead])
async def list_promotion_banners(
    db: DBSession,
    placement: str = Query(default="home", max_length=32),
):
    banners = await list_active_promotion_banners(db, placement=placement)
    return [PromotionBannerRead.model_validate(b) for b in banners]
