from fastapi import APIRouter

from app.routers.admin import (
    comments,
    dashboard,
    hero_featured,
    movies,
    payments,
    playback,
    promotions,
    series,
    subscription_plans,
    transcode,
)

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(dashboard.router)
router.include_router(movies.router)
router.include_router(playback.router)
router.include_router(transcode.router)
router.include_router(payments.router)
router.include_router(subscription_plans.router)
router.include_router(series.router)
router.include_router(comments.router)
router.include_router(promotions.router)
router.include_router(hero_featured.router)
