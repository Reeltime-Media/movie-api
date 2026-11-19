"""Public hero featured titles for the client storefront."""

from fastapi import APIRouter, Query

from app.core.apps import REELTIME
from app.dependencies import DBSession
from app.schemas.hero_featured import HeroFeaturedSlideRead
from app.services.hero_featured import app_for_placement, resolve_hero_slides
from app.services.response_cache import cache_get_or_set

router = APIRouter(prefix="/hero-featured", tags=["hero"])


@router.get("", response_model=list[HeroFeaturedSlideRead])
@router.get("/", response_model=list[HeroFeaturedSlideRead])
async def list_hero_featured(
    db: DBSession,
    placement: str = Query(default="home", max_length=32),
):
    # TV5's banner is served by /tv5/hero; Reeltime never shows TV5 slides.
    if app_for_placement(placement) != REELTIME:
        return []
    return await cache_get_or_set(
        f"hero:{placement}",
        lambda: resolve_hero_slides(db, placement=placement),
    )
