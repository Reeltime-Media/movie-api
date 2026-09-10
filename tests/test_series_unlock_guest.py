"""Guests can start a series Bakong unlock the same way as a movie."""

import inspect

from app.routers.payments import create_series_unlock_bakong_intent


def test_series_unlock_bakong_does_not_require_login():
    params = inspect.signature(create_series_unlock_bakong_intent).parameters
    assert "current_user" not in params
    assert "user" in params
    assert "response" in params
    annotation = str(params["user"].annotation)
    assert "OptionalUser" in annotation or "User | None" in annotation
