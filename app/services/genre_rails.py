"""Shim — genre rails live in ``app.catalog.genre_rails``."""

from app.catalog.genre_rails import (  # noqa: F401
    enrich_admin_genre_rail_items,
    resolve_genre_rails,
    validate_genre_rail_add,
)

__all__ = [
    "enrich_admin_genre_rail_items",
    "resolve_genre_rails",
    "validate_genre_rail_add",
]
