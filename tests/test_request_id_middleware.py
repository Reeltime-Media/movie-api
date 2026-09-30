"""Request ID middleware exposes X-Request-ID on every response."""

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

from fastapi.testclient import TestClient

from app import main as app_main

client = TestClient(app_main.app)


def test_health_live_gets_request_id_header():
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_client_request_id_is_echoed():
    response = client.get("/health/live", headers={"X-Request-ID": "client-corr-1"})
    assert response.headers.get("X-Request-ID") == "client-corr-1"
