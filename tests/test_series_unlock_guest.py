"""Guests can start a series Bakong unlock the same way as a movie."""

import os

os.environ["DEBUG"] = "false"
os.environ["SECRET_KEY"] = "unit-test-secret-key-0123456789abcdef"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://user:pass@localhost:5432/test"
os.environ["POOLER_DATABASE_URL"] = ""
os.environ["BARAY_API_KEY"] = ""
os.environ["TRANSCODE_SERVICE_URL"] = ""
os.environ["TRANSCODE_API_KEY"] = ""
os.environ.setdefault("R2_ACCOUNT_ID", "test")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("R2_BUCKET_NAME", "test")
os.environ.setdefault("R2_PUBLIC_URL", "https://cdn.test")

from app import main as app_main


def test_series_unlock_bakong_does_not_require_login():
    route = next(
        r
        for r in app_main.app.routes
        if getattr(r, "path", None) == "/payments/series/{slug}/unlock-bakong-intent"
        and "POST" in getattr(r, "methods", set())
    )

    names: list[str] = []

    def walk(dep):
        if dep.call is not None:
            names.append(getattr(dep.call, "__name__", type(dep.call).__name__))
        for child in dep.dependencies:
            walk(child)

    walk(route.dependant)
    assert "get_current_user" not in names
    assert "get_current_user_optional" in names
