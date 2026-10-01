import os

from fastapi.testclient import TestClient

os.environ["DEBUG"] = "false"
os.environ["SECRET_KEY"] = "unit-test-secret-key-0123456789abcdef"
os.environ["DATABASE_URL"] = "******localhost:5432/test"
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

client = TestClient(app_main.app)


def test_not_found_error_contract_includes_request_id():
    response = client.get("/missing", headers={"X-Request-ID": "req-404"})
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "http_404"
    assert body["message"] == "Not Found"
    assert body["request_id"] == "req-404"


def test_validation_error_contract():
    response = client.post("/auth/login", headers={"X-Request-ID": "req-422"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["message"] == "Invalid request parameters"
    assert body["request_id"] == "req-422"
    assert isinstance(body["details"], list)
