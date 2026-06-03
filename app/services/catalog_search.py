"""Shared text/genre filters for public movie and series catalog queries."""

from sqlalchemy import func, or_
from sqlalchemy.sql import Select


def apply_catalog_search[T](stmt: Select[tuple[T]], model: type[T], *, search: str | None) -> Select[tuple[T]]:
    if not search or not (term := search.strip()):
        return stmt
    pattern = f"%{term}%"
    genres_text = func.coalesce(func.array_to_string(model.genres, " "), "")
    return stmt.where(
        or_(
            model.title.ilike(pattern),
            func.coalesce(model.description, "").ilike(pattern),
            genres_text.ilike(pattern),
        )
    )


def apply_catalog_genre[T](stmt: Select[tuple[T]], model: type[T], *, genre: str | None) -> Select[tuple[T]]:
    if not genre or not (label := genre.strip()):
        return stmt
    return stmt.where(model.genres.contains([label]))
