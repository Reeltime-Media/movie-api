"""Catalog domain — public series/movies browse, hero, and rails.

HTTP stays at ``/series/*`` and ``/movies/*`` via existing routers (thinned
list/get/related handlers). CMS upload routes remain on those routers.
"""

from app.catalog.series import free_episode_counts_by_series, get_series_or_404

__all__ = [
    "free_episode_counts_by_series",
    "get_series_or_404",
]
