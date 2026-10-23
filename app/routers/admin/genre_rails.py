import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.genre_rail_item import GenreRailItem
from app.schemas.genre_rail import (
    GenreRailItemCreate,
    GenreRailItemRead,
    GenreRailItemUpdate,
)
from app.services.genre_rails import enrich_admin_genre_rail_items, validate_genre_rail_add
from app.services.response_cache import cache_delete

router = APIRouter()


async def _bust_public_genre_rails_cache() -> None:
    await cache_delete("genre-rails")


@router.get("/genre-rails", response_model=list[GenreRailItemRead])
async def list_admin_genre_rails(
    db: DBSession,
    _: AdminUser,
    genre: str | None = Query(default=None, description="Filter by genre name"),
):
    stmt = select(GenreRailItem).order_by(
        GenreRailItem.genre_name.asc(),
        GenreRailItem.sort_order.asc(),
        GenreRailItem.created_at.desc(),
    )
    if genre and genre.strip():
        stmt = stmt.where(GenreRailItem.genre_name == genre.strip())
    result = await db.execute(stmt)
    items = list(result.scalars().all())
    return await enrich_admin_genre_rail_items(db, items)


@router.post("/genre-rails", response_model=GenreRailItemRead, status_code=201)
async def create_admin_genre_rail(
    data: GenreRailItemCreate,
    db: DBSession,
    _: AdminUser,
):
    try:
        genre = await validate_genre_rail_add(db, data.genre_name, data.content_id)
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise NotFoundError(message) from exc
        raise ConflictError(message) from exc

    item = GenreRailItem(
        genre_name=genre,
        content_id=data.content_id,
        sort_order=data.sort_order,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    await _bust_public_genre_rails_cache()
    enriched = await enrich_admin_genre_rail_items(db, [item])
    return enriched[0]


@router.patch("/genre-rails/{item_id}", response_model=GenreRailItemRead)
async def update_admin_genre_rail(
    item_id: uuid.UUID,
    data: GenreRailItemUpdate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(select(GenreRailItem).where(GenreRailItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Genre rail item not found")

    item.sort_order = data.sort_order
    await db.commit()
    await db.refresh(item)
    await _bust_public_genre_rails_cache()
    enriched = await enrich_admin_genre_rail_items(db, [item])
    return enriched[0]


@router.delete("/genre-rails/{item_id}", status_code=204)
async def delete_admin_genre_rail(
    item_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(select(GenreRailItem).where(GenreRailItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Genre rail item not found")
    await db.delete(item)
    await db.commit()
    await _bust_public_genre_rails_cache()
