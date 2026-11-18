from decimal import Decimal

from app.billing.constants import SERIES_UNLOCK_PRICE_USD
from app.core.money import MIN_PAID_USD
from seed.pricing_catalog import (
    LEGACY_PLAN_CODES,
    PAID_MOVIE_PRICE_USD,
    PLAN_ACCESS_DESCRIPTION,
    SEED_PLANS,
    SERIES_PRICE_USD,
    apply_plan_fields,
    seed_plan_codes,
    should_overwrite_movie_price,
)


def test_catalog_prices():
    assert PAID_MOVIE_PRICE_USD == Decimal("0.50")
    assert SERIES_PRICE_USD == SERIES_UNLOCK_PRICE_USD == Decimal("2.50")
    assert MIN_PAID_USD == Decimal("0.03")


def test_seed_plans_match_card():
    by_code = {p["code"]: p for p in SEED_PLANS if p["audience"] == "app"}
    assert list(by_code) == [
        "basic_2w",
        "value_1m",
        "best_value_3m",
        "premium_5m",
        "testing_1m",
    ]
    assert by_code["basic_2w"]["price_usd"] == Decimal("3.49")
    assert by_code["basic_2w"]["billing_interval_days"] == 14
    assert by_code["value_1m"]["price_usd"] == Decimal("4.99")
    assert by_code["value_1m"]["billing_interval_days"] == 30
    assert by_code["best_value_3m"]["price_usd"] == Decimal("6.99")
    assert by_code["best_value_3m"]["billing_interval_days"] == 90
    assert by_code["premium_5m"]["price_usd"] == Decimal("10.99")
    assert by_code["premium_5m"]["billing_interval_days"] == 150
    assert by_code["testing_1m"]["price_usd"] == Decimal("0.03")
    assert by_code["testing_1m"]["billing_interval_days"] == 30
    assert by_code["testing_1m"]["name"] == "Testing"
    for plan in SEED_PLANS:
        assert plan["is_active"] is True
        assert PLAN_ACCESS_DESCRIPTION in plan["description"]


def test_legacy_codes_are_distinct():
    seed_codes = seed_plan_codes()
    assert set(LEGACY_PLAN_CODES).isdisjoint(seed_codes)
    assert "series_monthly" in LEGACY_PLAN_CODES
    assert seed_codes == {
        "basic_2w",
        "value_1m",
        "best_value_3m",
        "premium_5m",
        "testing_1m",
        "tv_3m",
        "tv_6m",
        "tv_12m",
    }


def test_tv_plans_are_3_6_12_months_and_tv_only():
    tv = {p["code"]: p for p in SEED_PLANS if p["audience"] == "tv"}
    assert list(tv) == ["tv_3m", "tv_6m", "tv_12m"]
    assert [p["billing_interval_days"] for p in tv.values()] == [90, 180, 365]
    assert [p["price_usd"] for p in tv.values()] == [
        Decimal("6.99"),
        Decimal("12.99"),
        Decimal("22.99"),
    ]
    # Longer packages are cheaper per month.
    monthly = [p["price_usd"] / months for p, months in zip(tv.values(), (3, 6, 12))]
    assert monthly == sorted(monthly, reverse=True)
    # Phone/web plans never carry the TV audience.
    assert all(p["audience"] == "app" for p in SEED_PLANS if p["code"] not in tv)


def test_free_movies_are_not_overwritten():
    assert should_overwrite_movie_price(is_free=True) is False
    assert should_overwrite_movie_price(is_free=False) is True


class _Plan:
    def __init__(self):
        self.name = "Old"
        self.description = "old"
        self.price_usd = Decimal("9.99")
        self.billing_interval_days = 30
        self.is_active = False
        self.sort_order = 9
        self.audience = "tv"


def test_apply_plan_fields_updates_existing():
    plan = _Plan()
    spec = SEED_PLANS[0]
    changed = apply_plan_fields(plan, spec)
    assert "price_usd" in changed
    assert plan.price_usd == spec["price_usd"]
    assert plan.name == spec["name"]
    assert plan.is_active is True
    assert apply_plan_fields(plan, spec) == []
