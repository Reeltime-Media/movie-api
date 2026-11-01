"""All-or-nothing reorder for home rails, hero slides, and promo banners."""

import asyncio
import uuid

import pytest

from app.models.hero_featured_item import HeroFeaturedItem
from app.models.home_section import HomeSectionItem
from app.models.promotion_banner import PromotionBanner
from app.services.hero_featured import reorder_hero_items
from app.services.home_sections import reorder_section_items
from app.services.promotion_banners import reorder_promotion_banners


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class FakeDb:
    def __init__(self, rows):
        self._rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self._rows)


def section_items(section_id, count):
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


def test_section_items_take_the_order_given():
    section_id = uuid.uuid4()
    items = section_items(section_id, 3)
    wanted = [items[2].id, items[0].id, items[1].id]

    asyncio.run(reorder_section_items(FakeDb(items), section_id, wanted))

    assert {item.id: item.sort_order for item in items} == {
        wanted[0]: 0,
        wanted[1]: 1,
        wanted[2]: 2,
    }


def test_section_items_reorder_is_a_single_query():
    section_id = uuid.uuid4()
    items = section_items(section_id, 12)
    db = FakeDb(items)

    asyncio.run(reorder_section_items(db, section_id, [i.id for i in reversed(items)]))

    assert len(db.statements) == 1


@pytest.mark.parametrize(
    ("label", "pick"),
    [
        ("missing item", lambda items: [items[0].id, items[1].id]),
        ("unknown item", lambda items: [i.id for i in items[:2]] + [uuid.uuid4()]),
        ("duplicate item", lambda items: [items[0].id, items[0].id, items[1].id]),
    ],
)
def test_section_items_reject_a_stale_list_without_changing_anything(label, pick):
    section_id = uuid.uuid4()
    items = section_items(section_id, 3)

    with pytest.raises(ValueError):
        asyncio.run(reorder_section_items(FakeDb(items), section_id, pick(items)))

    assert [item.sort_order for item in items] == [0, 1, 2], label


def test_hero_items_take_the_order_given():
    items = [HeroFeaturedItem(id=uuid.uuid4(), sort_order=index) for index in range(3)]
    wanted = [items[1].id, items[2].id, items[0].id]

    asyncio.run(reorder_hero_items(FakeDb(items), wanted))

    assert {item.id: item.sort_order for item in items} == {
        wanted[0]: 0,
        wanted[1]: 1,
        wanted[2]: 2,
    }


def test_hero_items_reject_unknown_ids_without_changing_anything():
    items = [HeroFeaturedItem(id=uuid.uuid4(), sort_order=index) for index in range(2)]

    with pytest.raises(ValueError):
        asyncio.run(reorder_hero_items(FakeDb(items), [items[1].id, uuid.uuid4()]))

    assert [item.sort_order for item in items] == [0, 1]


def test_banners_take_the_order_given():
    items = [PromotionBanner(id=uuid.uuid4(), sort_order=index) for index in range(3)]
    wanted = [items[2].id, items[1].id, items[0].id]

    asyncio.run(reorder_promotion_banners(FakeDb(items), wanted))

    assert {item.id: item.sort_order for item in items} == {
        wanted[0]: 0,
        wanted[1]: 1,
        wanted[2]: 2,
    }


def test_banners_reject_duplicates_without_changing_anything():
    items = [PromotionBanner(id=uuid.uuid4(), sort_order=index) for index in range(2)]

    with pytest.raises(ValueError):
        asyncio.run(reorder_promotion_banners(FakeDb(items), [items[1].id, items[1].id]))

    assert [item.sort_order for item in items] == [0, 1]
