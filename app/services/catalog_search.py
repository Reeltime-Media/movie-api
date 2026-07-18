"""Shared text/genre filters for public movie and series catalog queries."""

from __future__ import annotations

import re
from typing import TypeVar

from sqlalchemy import func, or_
from sqlalchemy.sql import Select

T = TypeVar("T")

# Keep letters/digits/Khmer/whitespace; strip tsquery operators and punctuation.
_TSQUERY_TOKEN_RE = re.compile(r"[^\w\u1780-\u17FF]+", re.UNICODE)


def prefix_tsquery(term: str) -> str | None:
    """Build a prefix tsquery like ``titan:* & ii:*`` for type-ahead search."""
    cleaned = _TSQUERY_TOKEN_RE.sub(" ", term).strip()
    if not cleaned:
        return None
    parts = [part for part in cleaned.split() if part]
    if not parts:
        return None
    return " & ".join(f"{part}:*" for part in parts)


def apply_catalog_search(stmt: Select[tuple[T]], model: type[T], *, search: str | None) -> Select[tuple[T]]:
    if not search or not (term := search.strip()):
        return stmt

    pattern = f"%{term}%"
    clauses = []

    search_vector = getattr(model, "search_vector", None)
    tsquery = prefix_tsquery(term)
    if search_vector is not None and tsquery:
        clauses.append(search_vector.op("@@")(func.to_tsquery("simple", tsquery)))

    # Substring match via pg_trgm GIN indexes — no coalesce() so indexes stay usable.
    clauses.append(model.title.ilike(pattern))
    title_km = getattr(model, "title_km", None)
    if title_km is not None:
        clauses.append(title_km.ilike(pattern))

    description = getattr(model, "description", None)
    if description is not None:
        clauses.append(description.ilike(pattern))

    genres = getattr(model, "genres", None)
    if genres is not None:
        clauses.append(func.array_to_string(genres, " ").ilike(pattern))

    return stmt.where(or_(*clauses))


def apply_catalog_genre(stmt: Select[tuple[T]], model: type[T], *, genre: str | None) -> Select[tuple[T]]:
    if not genre or not (label := genre.strip()):
        return stmt
    return stmt.where(model.genres.contains([label]))
