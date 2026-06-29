import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.dependencies import AdminUser, DBSession
from app.models.genre import Genre
from app.schemas.genre import GenreCreate, GenreRead

router = APIRouter(prefix="/genres", tags=["genres"])


@router.get("/", response_model=list[GenreRead])
async def list_genres(db: DBSession):
    result = await db.execute(select(Genre).order_by(Genre.name))
    return result.scalars().all()


@router.post("/", response_model=GenreRead, status_code=201)
async def create_genre(body: GenreCreate, _admin: AdminUser, db: DBSession):
    existing = await db.execute(select(Genre).where(Genre.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Genre already exists")

    genre = Genre(name=body.name)
    db.add(genre)
    await db.commit()
    await db.refresh(genre)
    return genre


@router.delete("/{genre_id}", status_code=204)
async def delete_genre(genre_id: uuid.UUID, _admin: AdminUser, db: DBSession):
    result = await db.execute(select(Genre).where(Genre.id == genre_id))
    genre = result.scalar_one_or_none()
    if genre is None:
        raise HTTPException(status_code=404, detail="Genre not found")
    await db.delete(genre)
    await db.commit()
