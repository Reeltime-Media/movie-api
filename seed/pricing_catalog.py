"""Canonical catalog and subscription prices for seed scripts."""

from decimal import Decimal

from app.billing.constants import SERIES_UNLOCK_PRICE_USD
from app.core.money import MIN_PAID_USD

PAID_MOVIE_PRICE_USD = Decimal("0.50")
SERIES_PRICE_USD = SERIES_UNLOCK_PRICE_USD

PLAN_ACCESS_DESCRIPTION = "Access to Series, Movies, Podcast, and News."

LEGACY_PLAN_CODES: tuple[str, ...] = (
    "series_monthly",
    "basic_monthly",
    "standard_monthly",
    "premium_annual",
)

SEED_PLANS: list[dict] = [
    {
        "code": "basic_2w",
        "name": "Basic",
        "description": f"2 weeks. {PLAN_ACCESS_DESCRIPTION}",
        "price_usd": Decimal("3.49"),
        "billing_interval_days": 14,
        "is_active": True,
        "sort_order": 0,
        "audience": "app",
        "bonus_days": 0,
    },
    {
        "code": "value_1m",
        "name": "Value",
        "description": f"1 month. {PLAN_ACCESS_DESCRIPTION}",
        "price_usd": Decimal("4.99"),
        "billing_interval_days": 30,
        "is_active": True,
        "sort_order": 1,
        "audience": "app",
        "bonus_days": 0,
    },
    {
        "code": "best_value_3m",
        "name": "Best Value",
        "description": f"3 months. {PLAN_ACCESS_DESCRIPTION}",
        "price_usd": Decimal("6.99"),
        "billing_interval_days": 90,
        "is_active": True,
        "sort_order": 2,
        "audience": "app",
        "bonus_days": 0,
    },
    {
        "code": "premium_5m",
        "name": "Premium",
        "description": f"5 months. {PLAN_ACCESS_DESCRIPTION}",
        "price_usd": Decimal("10.99"),
        "billing_interval_days": 150,
        "is_active": True,
        "sort_order": 3,
        "audience": "app",
        "bonus_days": 0,
    },
    {
        "code": "testing_1m",
        "name": "Testing",
        "description": f"Testing only — 1 month. {PLAN_ACCESS_DESCRIPTION}",
        "price_usd": MIN_PAID_USD,
        "billing_interval_days": 30,
        "is_active": True,
        "sort_order": 4,
        "audience": "app",
        "bonus_days": 0,
    },
    # The TV app's own packages (3 / 6 / 12 months). Sold only on TV, see audience.
    {
        "code": "tv_3m",
        "name": "TV 3 Months",
        "description": f"3 months. {PLAN_ACCESS_DESCRIPTION}",
        "price_usd": Decimal("15.00"),
        "billing_interval_days": 90,
        "is_active": True,
        "sort_order": 10,
        "audience": "tv",
        "bonus_days": 0,
    },
    {
        "code": "tv_6m",
        "name": "TV 6 Months",
        "description": f"6 months + 1 month free. {PLAN_ACCESS_DESCRIPTION}",
        "price_usd": Decimal("27.00"),
        "billing_interval_days": 210,  # 6 months + 1 free month
        "is_active": True,
        "sort_order": 11,
        "audience": "tv",
        "bonus_days": 30,
    },
    {
        "code": "tv_12m",
        "name": "TV 12 Months",
        "description": f"12 months + 2 months free. {PLAN_ACCESS_DESCRIPTION}",
        "price_usd": Decimal("50.00"),
        "billing_interval_days": 425,  # 12 months + 2 free months
        "is_active": True,
        "sort_order": 12,
        "audience": "tv",
        "bonus_days": 60,
    },
]

_PLAN_FIELDS = (
    "name",
    "description",
    "price_usd",
    "billing_interval_days",
    "is_active",
    "sort_order",
    "audience",
    "bonus_days",
)


def seed_plan_codes() -> set[str]:
    return {plan["code"] for plan in SEED_PLANS}


def should_overwrite_movie_price(*, is_free: bool) -> bool:
    return not is_free


def apply_plan_fields(plan: object, spec: dict) -> list[str]:
    changed: list[str] = []
    for field in _PLAN_FIELDS:
        new = spec[field]
        if getattr(plan, field) != new:
            setattr(plan, field, new)
            changed.append(field)
    return changed
