"""HTTP behaviour of the reorder endpoints: auth, status codes, cache busting."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("PIL")  # admin promotions imports image processing

from app.dependencies.auth import require_admin  # noqa: E402
from app.dependencies.db import get_db  # noqa: E402
from app.models.content import Content  # noqa: E402
from app.models.hero_featured_item import HeroFeaturedItem  # noqa: E402
from app.models.home_section import HomeSection, HomeSectionItem  # noqa: E402
from app.models.promotion_banner import PromotionBanner  # noqa: E402
from app.routers.admin import hero_featured, home_sections, movies, promotions  # noqa: E402


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDb:
    def __init__(self, rows, section=None):
        self.rows = rows
        self.section = section
        self.commits = 0

    async def execute(self, _statement):
        return FakeResult(self.rows)

    async def get(self, _model, _key):
        return self.section

    async def commit(self):
        self.commits += 1


@pytest.fixture
def client_for(monkeypatch):
    cleared: list[str] = []

    async def fake_cache_delete(key):
        cleared.append(key)

    async def fake_section(_db, section_id):
        return {
            "id": section_id,
            "type": "custom",
            "title": None,
            "genre_name": None,
            "is_visible": True,
            "sort_order": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "item_count": 0,
            "items": [],
        }

    for module in (home_sections, hero_featured, promotions):
        monkeypatch.setattr(module, "cache_delete", fake_cache_delete)
    monkeypatch.setattr(movies, "cache_delete_prefix", fake_cache_delete)
    monkeypatch.setattr(home_sections, "get_section_admin", fake_section)

    def build(db, *, admin=True):
        app = FastAPI()
        app.include_router(home_sections.router, prefix="/admin")
        app.include_router(hero_featured.router, prefix="/admin")
        app.include_router(promotions.router, prefix="/admin")
        app.include_router(movies.router, prefix="/admin")

        async def override_db():
            yield db

        app.dependency_overrides[get_db] = override_db
        if admin:
            app.dependency_overrides[require_admin] = lambda: object()
        client = TestClient(app, raise_server_exceptions=False)
        client.cleared = cleared
        return client

    return build


def section_rows(section_id, count):
    return [
        HomeSectionItem(
            id=uuid.uuid4(),
            section_id=section_id,
            item_kind="movie",
            ref_id=uuid.uuid4(),
            sort_order=index,
        )
        for index in range(count)
    ]


def test_rail_reorder_commits_once_and_clears_home_cache(client_for):
    section_id = uuid.uuid4()
    rows = section_rows(section_id, 3)
    db = FakeDb(rows, section=HomeSection(id=section_id, type="custom"))
    client = client_for(db)

    response = client.put(
        f"/admin/home-sections/{section_id}/items/reorder",
        json={"ids": [str(r.id) for r in reversed(rows)]},
    )

    assert response.status_code == 200
    assert [r.sort_order for r in rows] == [2, 1, 0]
    assert db.commits == 1
    assert "home-sections" in client.cleared


def test_rail_reorder_refuses_a_stale_list_without_saving(client_for):
    section_id = uuid.uuid4()
    rows = section_rows(section_id, 3)
    db = FakeDb(rows, section=HomeSection(id=section_id, type="custom"))
    client = client_for(db)

    response = client.put(
        f"/admin/home-sections/{section_id}/items/reorder",
        json={"ids": [str(rows[0].id)]},
    )

    assert response.status_code == 409
    assert db.commits == 0
    assert [r.sort_order for r in rows] == [0, 1, 2]


def test_rail_reorder_404s_for_an_unknown_section(client_for):
    client = client_for(FakeDb([], section=None))

    response = client.put(
        f"/admin/home-sections/{uuid.uuid4()}/items/reorder",
        json={"ids": [str(uuid.uuid4())]},
    )

    assert response.status_code == 404


def test_hero_reorder_saves_and_clears_each_placement(client_for):
    rows = [
        HeroFeaturedItem(id=uuid.uuid4(), sort_order=0, placement="home"),
        HeroFeaturedItem(id=uuid.uuid4(), sort_order=1, placement="home"),
    ]
    db = FakeDb(rows)
    client = client_for(db)

    response = client.put(
        "/admin/hero-featured/reorder", json={"ids": [str(rows[1].id), str(rows[0].id)]}
    )

    assert response.status_code == 204
    assert rows[1].sort_order == 0
    assert db.commits == 1
    assert {"hero:home", "home-sections"} <= set(client.cleared)


def test_banner_reorder_saves_and_clears_each_placement(client_for):
    rows = [
        PromotionBanner(id=uuid.uuid4(), sort_order=0, placement="home"),
        PromotionBanner(id=uuid.uuid4(), sort_order=1, placement="home"),
    ]
    db = FakeDb(rows)
    client = client_for(db)

    response = client.put(
        "/admin/promotion-banners/reorder", json={"ids": [str(rows[1].id), str(rows[0].id)]}
    )

    assert response.status_code == 204
    assert rows[1].sort_order == 0
    assert db.commits == 1
    assert {"promos:home", "home-sections"} <= set(client.cleared)


@pytest.mark.parametrize(
    "path",
    [
        f"/admin/home-sections/{uuid.uuid4()}/items/reorder",
        "/admin/hero-featured/reorder",
        "/admin/promotion-banners/reorder",
        "/admin/movies/reorder",
    ],
)
def test_reorder_requires_an_admin(client_for, path):
    db = FakeDb([])
    client = client_for(db, admin=False)

    response = client.put(path, json={"ids": [str(uuid.uuid4())]})

    assert response.status_code in (401, 403)
    assert db.commits == 0


@pytest.mark.parametrize(
    "path",
    ["/admin/hero-featured/reorder", "/admin/promotion-banners/reorder"],
)
def test_reorder_rejects_an_empty_list(client_for, path):
    db = FakeDb([])

    assert client_for(db).put(path, json={"ids": []}).status_code == 422


def test_movie_reorder_assigns_sequential_sort_order_and_clears_cache(client_for):
    movie_1 = Content(id=uuid.uuid4(), type="single", title="Movie 1", slug="m-1", sort_order=10)
    movie_2 = Content(id=uuid.uuid4(), type="single", title="Movie 2", slug="m-2", sort_order=20)
    db = FakeDb([movie_1, movie_2])
    client = client_for(db)

    # Reorder movie_2 first, then movie_1
    response = client.put(
        "/admin/movies/reorder",
        json={"ids": [str(movie_2.id), str(movie_1.id)]},
    )

    assert response.status_code == 204
    assert movie_2.sort_order == 0
    assert movie_1.sort_order == 1
    assert db.commits == 1
    assert "movies:" in client.cleared
