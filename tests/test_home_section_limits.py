"""Admin-set rail limits: what they allow, and what they refuse."""

import asyncio
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.auth import require_admin
from app.dependencies.db import get_db
from app.models.home_section import HomeSection
from app.routers.admin import home_sections
from app.services.home_sections import validate_item_add, validate_item_limit


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class FakeDb:
    """Finds the movie, finds no duplicate on the rail, and reports the item count."""

    def __init__(self, count):
        self.count = count

    async def execute(self, statement):
        text = str(statement).lower()
        if "count(" in text:
            return FakeResult(self.count)
        return FakeResult(None if "home_section_items" in text else uuid.uuid4())


def section(section_type="trending", limit=None):
    return HomeSection(id=uuid.uuid4(), type=section_type, item_limit=limit)


def add(db, rail):
    return validate_item_add(db, rail, item_kind="movie", ref_id=uuid.uuid4())


def test_a_raised_limit_allows_more_items_than_the_default():
    asyncio.run(add(FakeDb(12), section(limit=20)))


def test_the_chosen_limit_is_enforced():
    with pytest.raises(ValueError, match="limited to 20"):
        asyncio.run(add(FakeDb(20), section(limit=20)))


def test_a_lowered_limit_is_enforced():
    with pytest.raises(ValueError, match="limited to 5"):
        asyncio.run(add(FakeDb(5), section(limit=5)))


def test_no_choice_still_enforces_the_default():
    with pytest.raises(ValueError, match="limited to 12"):
        asyncio.run(add(FakeDb(12), section()))


def test_limit_can_match_the_items_already_picked():
    asyncio.run(validate_item_limit(FakeDb(7), section(), 7))


def test_limit_below_the_picked_items_is_refused():
    with pytest.raises(ValueError, match="Remove 2"):
        asyncio.run(validate_item_limit(FakeDb(7), section(), 5))


def test_reset_is_refused_when_items_exceed_the_default():
    with pytest.raises(ValueError, match="Remove 8"):
        asyncio.run(validate_item_limit(FakeDb(20), section(limit=30), None))


@pytest.mark.parametrize("section_type", ["hero", "banners", "plans"])
def test_sections_managed_elsewhere_are_refused(section_type):
    with pytest.raises(ValueError, match="can't be changed"):
        asyncio.run(validate_item_limit(FakeDb(0), section(section_type), 5))


class RouteDb:
    def __init__(self, rail, count):
        self.rail = rail
        self.count = count
        self.commits = 0

    async def execute(self, statement):
        if "count(" in str(statement).lower():
            return FakeResult(self.count)
        return FakeResult(self.rail)

    async def commit(self):
        self.commits += 1


@pytest.fixture
def patch_rail(monkeypatch):
    async def no_cache(_key):
        return None

    async def section_read(_db, section_id):
        return {
            "id": section_id,
            "type": "trending",
            "title": None,
            "genre_name": None,
            "is_visible": True,
            "sort_order": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }

    monkeypatch.setattr(home_sections, "cache_delete", no_cache)
    monkeypatch.setattr(home_sections, "get_section_admin", section_read)

    def send(db, body):
        app = FastAPI()
        app.include_router(home_sections.router, prefix="/admin")

        async def override_db():
            yield db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_admin] = lambda: object()
        client = TestClient(app, raise_server_exceptions=False)
        return client.patch(f"/admin/home-sections/{db.rail.id}", json=body)

    return send


def test_patch_saves_a_new_limit(patch_rail):
    db = RouteDb(section(), 3)

    assert patch_rail(db, {"item_limit": 20}).status_code == 200
    assert db.rail.item_limit == 20
    assert db.commits == 1


def test_patch_with_null_goes_back_to_the_default(patch_rail):
    db = RouteDb(section(limit=30), 3)

    assert patch_rail(db, {"item_limit": None}).status_code == 200
    assert db.rail.item_limit is None


def test_patch_without_the_field_leaves_the_limit_alone(patch_rail):
    db = RouteDb(section(limit=30), 3)

    assert patch_rail(db, {"is_visible": False}).status_code == 200
    assert db.rail.item_limit == 30


def test_patch_below_the_picked_items_saves_nothing(patch_rail):
    db = RouteDb(section(limit=30), 20)

    response = patch_rail(db, {"item_limit": 5})

    assert response.status_code == 409
    assert "Remove 15" in response.json()["detail"]
    assert db.rail.item_limit == 30
    assert db.commits == 0


def test_patch_above_the_maximum_is_rejected(patch_rail):
    db = RouteDb(section(), 3)

    assert patch_rail(db, {"item_limit": 51}).status_code == 422
    assert db.commits == 0
