"""Tests for app.main wiring: health endpoints, timeout handling, DB warmup.

Env vars are set before importing app.main because Settings and the engine
are constructed at import time.
"""

import json
import os

# Real env vars take precedence over .env, keeping these tests hermetic.
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

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import main as app_main

# No context manager: lifespan is intentionally not run, so no real DB is needed.
client = TestClient(app_main.app)


def _raise_timeout_in_module(module_name: str) -> TimeoutError:
    """Raise and capture a TimeoutError whose traceback claims the given module."""
    namespace = {"__name__": module_name}
    exec("def boom():\n    raise TimeoutError('timed out')", namespace)
    try:
        namespace["boom"]()
    except TimeoutError as exc:
        return exc
    raise AssertionError("unreachable")


class TestHealthEndpoints:
    def test_liveness_is_ok_without_database(self, monkeypatch):
        """Platform liveness probes must not restart the app when the DB is down."""
        monkeypatch.setattr(
            app_main,
            "verify_database_connection",
            AsyncMock(side_effect=AssertionError("liveness must not ping the DB")),
        )
        app_main.app.state.db_ready = True
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_readiness_ok_when_database_answers(self, monkeypatch):
        monkeypatch.setattr(
            "app.routers.health.verify_database_connection",
            AsyncMock(),
        )
        app_main.app.state.db_ready = True
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["database"] == "connected"

    def test_readiness_503_when_database_down(self, monkeypatch):
        monkeypatch.setattr(
            "app.routers.health.verify_database_connection",
            AsyncMock(side_effect=ConnectionError("db down")),
        )
        app_main.app.state.db_ready = True
        response = client.get("/health")
        assert response.status_code == 503
        assert app_main.app.state.db_ready is False
        app_main.app.state.db_ready = True  # restore for other tests


class TestTimeoutHandler:
    @pytest.mark.asyncio
    async def test_db_timeout_reports_database_unavailable(self):
        exc = _raise_timeout_in_module("asyncpg.connection")
        response = await app_main.timeout_error_handler(None, exc)
        assert response.status_code == 503
        body = json.loads(response.body)
        assert body["code"] == "database_timeout"
        assert "Database" in body["message"]
        assert "Supabase" in body["details"]

    @pytest.mark.asyncio
    async def test_non_db_timeout_is_not_blamed_on_database(self):
        exc = _raise_timeout_in_module("app.services.transcode_client")
        response = await app_main.timeout_error_handler(None, exc)
        assert response.status_code == 503
        body = json.loads(response.body)
        assert body["code"] == "request_timeout"
        assert "Database" not in body["message"]
        assert "timed out" in body["message"].lower()


class TestWarmupMiddleware:
    def test_probe_restores_db_ready_flag(self, monkeypatch):
        monkeypatch.setattr(app_main.db_warmup, "try_connect", AsyncMock(return_value=True))
        app_main.app.state.db_ready = False
        response = client.get("/health/live")
        assert response.status_code == 200
        assert app_main.app.state.db_ready is True

    def test_probe_skipped_when_db_ready(self, monkeypatch):
        probe = AsyncMock(return_value=True)
        monkeypatch.setattr(app_main.db_warmup, "try_connect", probe)
        app_main.app.state.db_ready = True
        client.get("/health/live")
        probe.assert_not_awaited()


class TestPaymentsExposure:
    def test_baray_routes_hidden_when_disabled(self):
        response = client.post("/payments/movies/00000000-0000-0000-0000-000000000000/intent")
        assert response.status_code == 404

    def test_bakong_watcher_routes_hidden_when_disabled(self):
        response = client.get("/payments/bakong/pending")
        assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
