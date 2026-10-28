"""Public home sections for the landing page builder."""

from fastapi import APIRouter

from app.dependencies import DBSession
from app.schemas.home_section import HomeSectionPublicRead
from app.services.home_sections import resolve_public_sections
from app.services.response_cache import cache_get_or_set

router = APIRouter(prefix="/home/sections", tags=["home-sections"])


@router.get("", response_model=list[HomeSectionPublicRead])
@router.get("/", response_model=list[HomeSectionPublicRead])
async def list_home_sections(db: DBSession):
    async def _load():
        return await resolve_public_sections(db)

    return await cache_get_or_set("home-sections", _load)
