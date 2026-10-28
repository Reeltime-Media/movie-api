from fastapi import APIRouter

from app.routers.admin import (
    coming_soon,
    comments,
    dashboard,
    free_today,
    genre_rails,
    hero_featured,
    home_sections,
    movies,
    payments,
    playback,
    podcasts,
    promotions,
    series,
    subscription_plans,
    transcode,
    tv_access_codes,
    tv_channels,
)

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(dashboard.router)
router.include_router(movies.router)
router.include_router(podcasts.router)
router.include_router(playback.router)
router.include_router(transcode.router)
router.include_router(tv_channels.router)
router.include_router(tv_access_codes.router)
router.include_router(payments.router)
router.include_router(subscription_plans.router)
router.include_router(series.router)
router.include_router(comments.router)
router.include_router(promotions.router)
router.include_router(hero_featured.router)
router.include_router(free_today.router)
router.include_router(coming_soon.router)
router.include_router(genre_rails.router)
router.include_router(home_sections.router)
