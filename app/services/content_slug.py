"""Shim — content slug helpers live in ``app.catalog.content_slug``."""

from app.catalog.content_slug import (  # noqa: F401
    slugify,
    unique_content_slug,
    unique_series_slug,
)

__all__ = ["slugify", "unique_content_slug", "unique_series_slug"]
