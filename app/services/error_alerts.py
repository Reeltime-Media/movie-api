"""Forward ERROR logs and unhandled exceptions to the ops alert relay.

The relay (ops/alert_relay, on Cloud Run) posts them to the Telegram alerts
group. `emit` only builds a small payload and queues it; one daemon thread
does the HTTP. Each process sends a given error at most once a minute, and
the relay folds repeats from every worker into one message per 10 minutes.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import queue
import sys
import threading
import time
import traceback
from typing import Any

import httpx
from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

_request_line: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "alert_request_line", default=None
)
# The relay client logs through these; alerting on them could loop.
_IGNORED_LOGGERS = ("httpx", "httpcore")
_TRACEBACK_LIMIT = 2500


class RequestLineMiddleware:
    """Remember "METHOD /path" so an error alert can say which request failed.

    Pure ASGI and added last (outermost), so it runs in uvicorn's own task and
    the value is still set when uvicorn logs an unhandled exception.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            _request_line.set(f"{scope['method']} {scope['path']}")
        await self.app(scope, receive, send)


def _first_line(text: str) -> str:
    # SQLAlchemy puts the SQL and bound parameters (emails, ids) on later lines.
    return (text.strip().splitlines() or [""])[0][:300]


def build_alert(record: logging.LogRecord, service: str) -> dict[str, Any]:
    """Relay payload for one log record. Must run in the logging thread."""
    message = record.getMessage()
    title = _first_line(message)
    details: list[str] = []
    request_line = _request_line.get()
    if request_line:
        details.append(request_line)

    exc = record.exc_info[1] if record.exc_info else None
    where = ""
    if exc is not None:
        title = f"{type(exc).__name__}: {_first_line(str(exc))}"
        frames = traceback.extract_tb(exc.__traceback__)
        if frames:
            where = f"{frames[-1].filename}:{frames[-1].lineno}"
        details.append(_first_line(message))
        details.append("".join(traceback.format_tb(exc.__traceback__))[-_TRACEBACK_LIMIT:])
    details.append(f"logger: {record.name}")

    raw = "|".join(
        (service, record.name, str(record.msg), type(exc).__name__ if exc else "", where)
    )
    return {
        "source": service,
        "level": "error",
        "title": title,
        "detail": "\n".join(details),
        "fingerprint": hashlib.sha1(raw.encode()).hexdigest()[:16],
    }


class AlertRelayHandler(logging.Handler):
    """Queue ERROR records for the relay; a daemon thread does the posting."""

    def __init__(
        self,
        url: str,
        token: str,
        service: str,
        *,
        throttle_seconds: float = 60,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(level=logging.ERROR)
        self._url = url.rstrip("/") + "/event"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._service = service
        self._throttle = throttle_seconds
        self._transport = transport
        self._last_sent: dict[str, float] = {}
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
        threading.Thread(target=self._drain, name="alert-relay", daemon=True).start()

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_IGNORED_LOGGERS):
            return
        try:
            alert = build_alert(record, self._service)
            now = time.monotonic()
            last = self._last_sent.get(alert["fingerprint"])
            if last is not None and now - last < self._throttle:
                return
            self._last_sent[alert["fingerprint"]] = now
            self._queue.put_nowait(alert)
        except queue.Full:
            pass
        except Exception:
            self.handleError(record)

    def _drain(self) -> None:
        with httpx.Client(timeout=5, transport=self._transport) as client:
            while True:
                alert = self._queue.get()
                # stderr, not logging: an ERROR log here would re-enter this handler.
                try:
                    res = client.post(self._url, headers=self._headers, json=alert)
                    if res.status_code >= 400:
                        print(f"alert relay: HTTP {res.status_code}", file=sys.stderr, flush=True)
                except httpx.HTTPError as exc:
                    print(f"alert relay unreachable: {exc!r}", file=sys.stderr, flush=True)


def install_error_alerts(app: FastAPI, *, url: str, token: str, service: str = "api") -> None:
    """Send this process's ERROR logs to the relay. No-op without URL + token.

    Call after every other middleware is added so RequestLineMiddleware ends
    up outermost.
    """
    url, token = url.strip(), token.strip()
    if not url or not token:
        return
    root = logging.getLogger()
    if not root.handlers:
        # Any root handler switches off logging.lastResort, which is what
        # prints app warnings and errors to stderr today. Keep that output.
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        root.addHandler(console)
    handler = AlertRelayHandler(url, token, service)
    root.addHandler(handler)
    # Unhandled request exceptions are logged here, and it doesn't propagate to root.
    logging.getLogger("uvicorn.error").addHandler(handler)
    app.add_middleware(RequestLineMiddleware)
