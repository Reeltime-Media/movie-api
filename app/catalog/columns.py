"""Column projections for catalog list/rail queries.

List DTOs only need a subset of Content/Series columns. Loading full rows
pulls heavy fields (search_vector, hls_master_key, etc.) on every catalog
request — use these helpers with ``select(...).options(...)``.
"""

from __future__ import annotations

from sqlalchemy.orm import Load, load_only

from app.models.content import Content
from app.models.series import Series

CONTENT_LIST_COLUMNS = (
    Content.id,
    Content.type,
    Content.slug,
    Content.title,
    Content.title_km,
    Content.description,
    Content.genres,
    Content.region,
    Content.poster_key,
    Content.banner_key,
    Content.price_usd,
    Content.rating,
    Content.runtime,
    Content.release_year,
    Content.is_free,
    Content.trailer_url,
    Content.updated_at,
)

SERIES_LIST_COLUMNS = (
    Series.id,
    Series.slug,
    Series.title,
    Series.title_km,
    Series.genres,
    Series.release_year,
    Series.rating,
    Series.poster_key,
    Series.banner_key,
    Series.monthly_price_usd,
    Series.is_short_movie,
    Series.updated_at,
)

# Hero slides need description + trailer for series (not on SeriesListItemRead).
SERIES_HERO_COLUMNS = (
    *SERIES_LIST_COLUMNS,
    Series.description,
    Series.trailer_url,
)


def content_list_load_options() -> Load:
    return load_only(*CONTENT_LIST_COLUMNS)


def series_list_load_options() -> Load:
    return load_only(*SERIES_LIST_COLUMNS)


def series_hero_load_options() -> Load:
    return load_only(*SERIES_HERO_COLUMNS)
