"""What the admin learns about a section from the API, so it holds no copies of these rules."""

import uuid
from datetime import UTC, datetime

import pytest

from app.schemas.home_section import SECTION_CAPS, HomeSectionAdminRead


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
