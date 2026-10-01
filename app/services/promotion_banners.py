"""Shim — promotion banners live in ``app.catalog.promotion_banners``."""

from app.catalog.promotion_banners import (  # noqa: F401
    list_active_promotion_banners,
)

__all__ = ["list_active_promotion_banners"]
