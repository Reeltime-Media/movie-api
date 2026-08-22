"""Canonical catalog and subscription prices for seed scripts."""

from decimal import Decimal

PAID_MOVIE_PRICE_USD = Decimal("0.50")
SERIES_PRICE_USD = Decimal("2.50")

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
    },
    {
        "code": "value_1m",
        "name": "Value",
        "description": f"1 month. {PLAN_ACCESS_DESCRIPTION}",
        "price_usd": Decimal("4.99"),
        "billing_interval_days": 30,
        "is_active": True,
        "sort_order": 1,
    },
    {
        "code": "best_value_3m",
        "name": "Best Value",
        "description": f"3 months. {PLAN_ACCESS_DESCRIPTION}",
        "price_usd": Decimal("6.99"),
        "billing_interval_days": 90,
        "is_active": True,
        "sort_order": 2,
    },
    {
        "code": "premium_5m",
        "name": "Premium",
        "description": f"5 months. {PLAN_ACCESS_DESCRIPTION}",
        "price_usd": Decimal("10.99"),
        "billing_interval_days": 150,
        "is_active": True,
        "sort_order": 3,
    },
]

_PLAN_FIELDS = (
    "name",
    "description",
    "price_usd",
    "billing_interval_days",
    "is_active",
    "sort_order",
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
