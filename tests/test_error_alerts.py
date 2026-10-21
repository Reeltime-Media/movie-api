"""Error alerts: payload, privacy, throttling, and FastAPI wiring."""

import json
import logging
import threading

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.error_alerts import (
    AlertRelayHandler,
    RequestLineMiddleware,
    build_alert,
    install_error_alerts,
)


def _raised(exc: Exception) -> Exception:
    try:
        raise exc
    except Exception as caught:
        return caught


def _record(
    msg: str = "boom %s",
    args: tuple = ("x",),
    exc: Exception | None = None,
    name: str = "app.test",
) -> logging.LogRecord:
    exc_info = (type(exc), exc, exc.__traceback__) if exc else None
    return logging.LogRecord(name, logging.ERROR, __file__, 10, msg, args, exc_info)


def _relay(received: list[httpx.Request], arrived: threading.Event) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        received.append(request)
        arrived.set()
        return httpx.Response(202, json={"sent": True})

    return httpx.MockTransport(respond)


def test_exception_alert_names_the_type_and_drops_sql_parameters() -> None:
    exc = _raised(ValueError("duplicate key\n[parameters: ('someone@example.com',)]"))

    alert = build_alert(_record("Database error", (), exc), "api")

    assert alert["source"] == "api"
    assert alert["level"] == "error"
    assert alert["title"] == "ValueError: duplicate key"
    assert "someone@example.com" not in alert["title"] + alert["detail"]
    assert "test_error_alerts.py" in alert["detail"]
    assert "logger: app.test" in alert["detail"]


def test_fingerprint_groups_by_message_template_not_arguments() -> None:
    first = build_alert(_record("failed for %s", ("1",)), "api")
    second = build_alert(_record("failed for %s", ("2",)), "api")
    other = build_alert(_record("other %s", ("1",)), "api")

    assert first["fingerprint"] == second["fingerprint"]
    assert first["fingerprint"] != other["fingerprint"]


def test_alert_inside_a_request_names_the_request() -> None:
    seen: list[dict] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(build_alert(record, "api"))

    logger = logging.getLogger("tests.error_alerts.request")
    capture = Capture(level=logging.ERROR)
    logger.addHandler(capture)
    app = FastAPI()

    @app.get("/movies/{slug}")
    async def movie(slug: str) -> dict:
        logger.error("lookup failed for %s", slug)
        return {}

    app.add_middleware(RequestLineMiddleware)
    try:
        TestClient(app).get("/movies/abc")
    finally:
        logger.removeHandler(capture)

    assert seen[0]["detail"].startswith("GET /movies/abc\n")


def test_handler_posts_a_repeated_error_once_per_throttle_window() -> None:
    received: list[httpx.Request] = []
    arrived = threading.Event()
    handler = AlertRelayHandler(
        "https://relay.test/", "tok", "api", transport=_relay(received, arrived)
    )

    handler.handle(_record())
    handler.handle(_record())

    assert arrived.wait(5)
    assert len(received) == 1
    assert handler._queue.empty()
    assert str(received[0].url) == "https://relay.test/event"
    assert received[0].headers["authorization"] == "Bearer tok"
    assert json.loads(received[0].content)["title"] == "boom x"


def test_handler_ignores_the_http_client_loggers() -> None:
    handler = AlertRelayHandler(
        "https://relay.test", "tok", "api", transport=_relay([], threading.Event())
    )

    handler.handle(_record(name="httpx"))
    handler.handle(_record(name="httpcore.connection"))

    assert handler._last_sent == {}


def test_install_without_url_changes_nothing() -> None:
    app = FastAPI()
    before = list(logging.getLogger().handlers)

    install_error_alerts(app, url="", token="tok")

    assert logging.getLogger().handlers == before
    assert app.user_middleware == []


def test_install_wires_handlers_and_middleware_and_keeps_console_output(monkeypatch) -> None:
    root = logging.getLogger()
    uvicorn_error = logging.getLogger("uvicorn.error")
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(uvicorn_error, "handlers", [])
    app = FastAPI()

    install_error_alerts(app, url="https://relay.test", token="tok")

    console = [h for h in root.handlers if type(h) is logging.StreamHandler]
    assert console and console[0].level == logging.WARNING
    assert any(isinstance(h, AlertRelayHandler) for h in root.handlers)
    assert any(isinstance(h, AlertRelayHandler) for h in uvicorn_error.handlers)
    assert app.user_middleware[0].cls is RequestLineMiddleware
