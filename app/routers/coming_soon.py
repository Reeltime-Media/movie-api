"""Public Coming Soon picks for the client home page."""

from fastapi import APIRouter

from app.dependencies import DBSession
from app.schemas.content import ContentListItemRead
from app.services.coming_soon import resolve_coming_soon_movies
from app.services.response_cache import cache_get_or_set

router = APIRouter(prefix="/coming-soon", tags=["coming-soon"])


@router.get("", response_model=list[ContentListItemRead])
@router.get("/", response_model=list[ContentListItemRead])
async def list_coming_soon(db: DBSession):
    async def _load():
        movies = await resolve_coming_soon_movies(db)
        return [ContentListItemRead.model_validate(movie) for movie in movies]

    return await cache_get_or_set("coming-soon", _load)
