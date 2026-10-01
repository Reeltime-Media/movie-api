"""Shim — hero featured lives in ``app.catalog.hero_featured``."""

from app.catalog.hero_featured import (  # noqa: F401
    _build_slide,
    enrich_admin_hero_items,
    list_active_hero_items,
    resolve_hero_slides,
    validate_hero_content,
)

__all__ = [
    "_build_slide",
    "enrich_admin_hero_items",
    "list_active_hero_items",
    "resolve_hero_slides",
    "validate_hero_content",
]
