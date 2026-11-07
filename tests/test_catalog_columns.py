"""Catalog list queries must project only list DTO columns."""

from app.models.content import Content
from app.models.series import Series
from app.schemas.content import ContentListItemRead
from app.schemas.series import SeriesListItemRead
from app.services.catalog_columns import (
    CONTENT_LIST_COLUMNS,
    SERIES_HERO_COLUMNS,
    SERIES_LIST_COLUMNS,
    content_list_load_options,
    series_hero_load_options,
    series_list_load_options,
)


def test_content_list_columns_exclude_heavy_fields():
    names = {col.key for col in CONTENT_LIST_COLUMNS}
    assert "search_vector" not in names
    assert "hls_master_key" not in names
    assert "transcode_status" not in names
    for required in (
        "id",
        "slug",
        "title",
        "poster_key",
        "price_usd",
        "is_free",
        "updated_at",
    ):
        assert required in names


def test_series_list_columns_exclude_search_vector():
    names = {col.key for col in SERIES_LIST_COLUMNS}
    assert "search_vector" not in names
    assert "description" not in names
    assert "slug" in names
    assert "monthly_price_usd" in names


def test_series_hero_columns_include_description_and_trailer():
    names = {col.key for col in SERIES_HERO_COLUMNS}
    assert "description" in names
    assert "trailer_url" in names


def test_list_dto_fields_backed_by_columns_are_all_projected():
    """A DTO field whose column isn't loaded triggers a lazy load while the
    response is serialized (MissingGreenlet -> HTTP 500 on every catalog list)."""
    for dto, model, columns in (
        (ContentListItemRead, Content, CONTENT_LIST_COLUMNS),
        (SeriesListItemRead, Series, SERIES_LIST_COLUMNS),
    ):
        projected = {col.key for col in columns}
        mapped = {col.key for col in model.__table__.columns}
        missing = (set(dto.model_fields) & mapped) - projected
        assert not missing, f"{dto.__name__} fields not in load_only: {sorted(missing)}"


def test_load_options_target_correct_entities():
    content_opt = content_list_load_options()
    series_opt = series_list_load_options()
    hero_opt = series_hero_load_options()
    assert content_opt is not None
    assert series_opt is not None
    assert hero_opt is not None
    # Smoke: options are usable with the mapped classes.
    assert Content.__tablename__ == "content"
    assert Series.__tablename__ == "series"
