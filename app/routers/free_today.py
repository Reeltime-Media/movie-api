"""Public "Free movies today" picks for the client home page."""

from fastapi import APIRouter

from app.dependencies import DBSession
from app.schemas.content import ContentListItemRead
from app.services.free_today import resolve_free_today_movies

router = APIRouter(prefix="/free-today", tags=["free-today"])


@router.get("/", response_model=list[ContentListItemRead])
async def list_free_today(db: DBSession):
    movies = await resolve_free_today_movies(db)
    return [ContentListItemRead.model_validate(movie) for movie in movies]
