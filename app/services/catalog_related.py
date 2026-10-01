"""Shim — related catalog lives in ``app.catalog.related``."""

from app.catalog.related import (  # noqa: F401
    related_movies,
    related_series,
)

__all__ = ["related_movies", "related_series"]
