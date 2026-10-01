"""Shim — catalog search lives in ``app.catalog.search``."""

from app.catalog.search import (  # noqa: F401
    apply_catalog_genre,
    apply_catalog_search,
    prefix_tsquery,
)

__all__ = [
    "apply_catalog_genre",
    "apply_catalog_search",
    "prefix_tsquery",
]
