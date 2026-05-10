"""Baray payment gateway integration stub.

Fill in create_intent() and any other calls following Baray's API docs.
The webhook handler in routers/webhooks.py calls verify_signature() before
trusting any incoming payload.
"""

import hashlib
import hmac

from app.config import get_settings

settings = get_settings()


def verify_signature(payload: bytes, signature: str) -> bool:
    """Constant-time HMAC-SHA256 comparison against Baray's webhook secret."""
    expected = hmac.new(
        settings.baray_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
