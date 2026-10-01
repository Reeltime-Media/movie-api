"""Shim — series helpers live in ``app.catalog.series``."""

from app.catalog.series import (  # noqa: F401
    free_episode_counts_by_series,
    get_series_or_404,
)

__all__ = ["free_episode_counts_by_series", "get_series_or_404"]
