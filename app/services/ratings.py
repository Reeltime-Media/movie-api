"""Shim — ratings live in ``app.catalog.ratings``."""

from app.catalog.ratings import (  # noqa: F401
    assert_rateable_movie,
    upsert_rating,
)

__all__ = ["assert_rateable_movie", "upsert_rating"]
