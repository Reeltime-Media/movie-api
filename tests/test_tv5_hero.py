"""The TV5 home banner: TV5 slides feature TV5 titles only, and never reach Reeltime."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.models.hero_featured_item import HeroFeaturedItem
from app.routers import hero_featured as public_hero
from app.services import hero_featured


class FakeResult:
    def __init__(self, scalar=None, rows=()):
        self._scalar = scalar
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class FakeDb:
    def __init__(self, *results):
        self._results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0)


def params(statement):
    values = statement.compile(dialect=postgresql.dialect()).params.values()
    return {v for value in values for v in (value if isinstance(value, list) else [value])}


@pytest.mark.parametrize(
    ("placement", "app"),
    [("tv5_home", "tv5"), ("tv5", "tv5"), ("home", "reeltime"), ("series", "reeltime")],
)
def test_placement_decides_the_app(placement, app):
    assert hero_featured.app_for_placement(placement) == app


@pytest.mark.parametrize("kind", ["movie", "series"])
def test_tv5_slide_can_only_feature_a_tv5_title(kind):
    db = FakeDb(FakeResult(scalar=uuid.uuid4()))
    asyncio.run(
        hero_featured.validate_hero_content(
            db, content_type=kind, content_id=uuid.uuid4(), placement="tv5_home"
        )
    )
    assert "tv5" in params(db.statements[0])
    assert "reeltime" not in params(db.statements[0])


def test_reeltime_slide_still_features_reeltime_titles_only():
    db = FakeDb(FakeResult(scalar=uuid.uuid4()))
    asyncio.run(
        hero_featured.validate_hero_content(db, content_type="movie", content_id=uuid.uuid4())
    )
    assert "reeltime" in params(db.statements[0])


def test_tv5_slide_naming_a_reeltime_title_is_refused():
    db = FakeDb(FakeResult(scalar=None))
    with pytest.raises(ValueError, match="Series not found"):
        asyncio.run(
            hero_featured.validate_hero_content(
                db, content_type="series", content_id=uuid.uuid4(), placement="tv5_home"
            )
        )


def test_tv5_banner_only_resolves_tv5_titles(monkeypatch):
    series_id = uuid.uuid4()
    item = HeroFeaturedItem(
        id=uuid.uuid4(),
        content_type="series",
        content_id=series_id,
        placement="tv5_home",
        is_active=True,
        sort_order=0,
    )

    async def active(_db, *, placement):
        assert placement == "tv5_home"
        return [item]

    monkeypatch.setattr("app.catalog.hero_featured.list_active_hero_items", active)
    db = FakeDb(FakeResult(rows=[]))
    slides = asyncio.run(hero_featured.resolve_hero_slides(db, placement="tv5_home"))
    assert slides == []
    assert "tv5" in params(db.statements[0])
    assert "reeltime" not in params(db.statements[0])


def test_reeltime_hero_endpoint_never_serves_tv5_slides(monkeypatch):
    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("TV5 slides must not be resolved for Reeltime")

    monkeypatch.setattr(public_hero, "cache_get_or_set", must_not_run)
    assert asyncio.run(public_hero.list_hero_featured(db=None, placement="tv5_home")) == []


def test_a_slide_cannot_move_between_reeltime_and_tv5():
    from app.core.exceptions import ConflictError
    from app.routers.admin.hero_featured import update_admin_hero_featured
    from app.schemas.hero_featured import HeroFeaturedItemUpdate

    item = HeroFeaturedItem(
        id=uuid.uuid4(),
        content_type="series",
        content_id=uuid.uuid4(),
        placement="home",
        is_active=True,
        sort_order=0,
    )
    db = FakeDb(FakeResult(scalar=item))
    with pytest.raises(ConflictError, match="between Reeltime and TV5"):
        asyncio.run(
            update_admin_hero_featured(
                item.id, HeroFeaturedItemUpdate(placement="tv5_home"), db, None
            )
        )
    assert item.placement == "home"
