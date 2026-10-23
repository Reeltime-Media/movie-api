"""Public home genre rails curated by admin."""

from fastapi import APIRouter

from app.dependencies import DBSession
from app.schemas.genre_rail import GenreRailRead
from app.services.genre_rails import resolve_genre_rails
from app.services.response_cache import cache_get_or_set

router = APIRouter(prefix="/genre-rails", tags=["genre-rails"])


@router.get("", response_model=list[GenreRailRead])
@router.get("/", response_model=list[GenreRailRead])
async def list_genre_rails(db: DBSession):
    async def _load():
        return await resolve_genre_rails(db)

    return await cache_get_or_set("genre-rails", _load)
