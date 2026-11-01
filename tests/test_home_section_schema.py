"""What the admin learns about a section from the API, so it holds no copies of these rules."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.home_section import (
    MAX_SECTION_ITEM_LIMIT,
    SECTION_CAPS,
    HomeSectionAdminRead,
    HomeSectionUpdate,
)


def read(section_type):
    now = datetime.now(UTC)
    return HomeSectionAdminRead(
        id=uuid.uuid4(),
        type=section_type,
        title=None,
        genre_name=None,
        is_visible=True,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize("section_type", sorted(SECTION_CAPS))
def test_item_limit_matches_the_enforced_cap(section_type):
    assert read(section_type).item_limit == SECTION_CAPS[section_type]


def test_sections_without_items_have_no_limit():
    assert read("plans").item_limit is None


@pytest.mark.parametrize(
    "section_type",
    ["hero", "banners", "tv", "free_today", "trending", "most_watched", "coming_soon", "series"],
)
def test_rails_with_a_fallback_are_auto_filled(section_type):
    assert read(section_type).auto_filled is True


@pytest.mark.parametrize("section_type", ["genre", "custom", "plans"])
def test_rails_without_a_fallback_are_not_auto_filled(section_type):
    assert read(section_type).auto_filled is False


def test_rules_reach_the_json_the_admin_receives():
    payload = read("trending").model_dump(mode="json")

    assert payload["item_limit"] == 12
    assert payload["auto_filled"] is True


def read_with_limit(section_type, limit):
    now = datetime.now(UTC)
    return HomeSectionAdminRead(
        id=uuid.uuid4(),
        type=section_type,
        title=None,
        genre_name=None,
        is_visible=True,
        sort_order=0,
        created_at=now,
        updated_at=now,
        item_limit=limit,
    )


def test_a_rail_uses_the_limit_an_admin_chose():
    section = read_with_limit("trending", 20)

    assert section.item_limit == 20
    assert section.default_item_limit == 12
    assert section.max_item_limit == MAX_SECTION_ITEM_LIMIT


def test_a_rail_with_no_choice_keeps_its_default():
    assert read_with_limit("most_watched", None).item_limit == 10


@pytest.mark.parametrize("section_type", ["hero", "banners", "plans"])
def test_sections_managed_elsewhere_cannot_have_their_limit_changed(section_type):
    section = read_with_limit(section_type, 40)

    assert section.item_limit == SECTION_CAPS.get(section_type)
    assert section.max_item_limit is None


def test_reading_a_section_twice_keeps_the_same_limit():
    first = read_with_limit("genre", 30)

    assert HomeSectionAdminRead.model_validate(first).item_limit == 30


@pytest.mark.parametrize("value", [0, -1, MAX_SECTION_ITEM_LIMIT + 1])
def test_update_rejects_limits_out_of_range(value):
    with pytest.raises(ValidationError):
        HomeSectionUpdate(item_limit=value)


def test_update_accepts_a_limit_and_a_reset_to_default():
    assert HomeSectionUpdate(item_limit=MAX_SECTION_ITEM_LIMIT).item_limit == 50
    assert HomeSectionUpdate(item_limit=None).model_dump(exclude_unset=True) == {"item_limit": None}
