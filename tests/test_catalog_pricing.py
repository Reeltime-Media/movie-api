"""Unit tests for public catalog pricing endpoint."""

from decimal import Decimal

from app.billing.constants import SERIES_UNLOCK_PRICE_USD
from app.billing.router import get_catalog_pricing
from app.core.money import MIN_PAID_USD


def test_get_catalog_pricing():
    pricing = get_catalog_pricing()
    assert pricing.series_unlock_usd == SERIES_UNLOCK_PRICE_USD == Decimal("2.50")
    assert pricing.min_paid_usd == MIN_PAID_USD == Decimal("0.03")
