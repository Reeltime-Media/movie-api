"""The home page hero shows every active slide of the admin's Hero carousel screen."""

import asyncio
import uuid

from app.catalog import hero_featured, home_sections
from app.models.hero_featured_item import HeroFeaturedItem
from app.models.home_section import HomeSection, HomeSectionItem
from app.schemas.hero_featured import HeroFeaturedSlideRead


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return FakeScalars(self._rows)


class FakeDb:
    """Answers the queries resolve_public_sections makes for a page that only has a hero section."""

    def __init__(self, sections, items, linked_heroes=()):
        self.sections = sections
        self.items = items
        self.linked_heroes = list(linked_heroes)

    async def execute(self, statement):
        text = str(statement).lower()
        if "hero_featured_items" in text:
            return FakeResult(self.linked_heroes)
        if "home_section_items" in text:
            return FakeResult(self.items)
        return FakeResult(self.sections)


def slide(order: int) -> HeroFeaturedSlideRead:
    return HeroFeaturedSlideRead(
        id=uuid.uuid4(),
        content_type="custom",
        title=f"slide {order}",
        slug="",
        description=None,
        genres=[],
        release_year=None,
        rating=None,
        runtime=None,
        poster_key=None,
        sort_order=order,
    )


def run(db, monkeypatch, slides):
    async def fake_resolve(_db, *, placement="home"):
        assert placement == "home"
        return slides

    monkeypatch.setattr(hero_featured, "resolve_hero_slides", fake_resolve)
    return asyncio.run(home_sections.resolve_public_sections(db))


def test_a_slide_added_after_the_section_was_linked_still_shows(monkeypatch):
    # The section only links 3 of the 4 slides (what the old one-time migration left behind);
    # the first slide, added later in the Hero carousel screen, used to be missing.
    hero = HomeSection(id=uuid.uuid4(), type="hero", is_visible=True, sort_order=0)
    linked_heroes = [
        HeroFeaturedItem(id=uuid.uuid4(), content_type="custom", title=f"slide {n}", sort_order=n)
        for n in (1, 2, 3)
    ]
    linked = [
        HomeSectionItem(
            id=uuid.uuid4(),
            section_id=hero.id,
            item_kind="hero_slide",
            ref_id=h.id,
            sort_order=h.sort_order,
        )
        for h in linked_heroes
    ]
    slides = [slide(n) for n in (0, 1, 2, 3)]

    public = run(FakeDb([hero], linked, linked_heroes), monkeypatch, slides)

    assert [s.sort_order for s in public[0].hero_slides] == [0, 1, 2, 3]


def test_a_hero_section_with_no_linked_items_shows_the_slides(monkeypatch):
    hero = HomeSection(id=uuid.uuid4(), type="hero", is_visible=True, sort_order=0)

    public = run(FakeDb([hero], []), monkeypatch, [slide(0), slide(1)])

    assert [s.sort_order for s in public[0].hero_slides] == [0, 1]


def test_the_hero_cap_still_applies(monkeypatch):
    hero = HomeSection(id=uuid.uuid4(), type="hero", is_visible=True, sort_order=0)
    many = [slide(n) for n in range(15)]

    public = run(FakeDb([hero], []), monkeypatch, many)

    assert len(public[0].hero_slides) == 10
    assert [s.sort_order for s in public[0].hero_slides] == list(range(10))
