from decimal import Decimal

MIN_PAID_USD = Decimal("0.03")


def validate_usd_price(amount: Decimal) -> Decimal:
    """USD price must be exactly 0 (free) or at least MIN_PAID_USD."""
    if amount < 0:
        raise ValueError("Price cannot be negative.")
    if amount == 0:
        return amount
    if amount >= MIN_PAID_USD:
        return amount
    raise ValueError("Price must be 0 (free) or at least 0.03 USD.")
