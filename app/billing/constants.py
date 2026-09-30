"""Billing constants shared by intent creation."""

from decimal import Decimal

# Flat one-time price to unlock a single series — matches the "Mini" pricing
# card (lib/pricing-tiers.ts on the client); series have no per-title unlock
# price of their own (Series.monthly_price_usd is for the old subscription-only
# design), so this is a constant rather than something resolved per series.
SERIES_UNLOCK_PRICE_USD = Decimal("2.50")
