"""Reeltime alert relay: forwards ops alerts to one Telegram chat.

Runs on Cloud Run, outside the VMs, so "site down" alerts still arrive when a
VM is down. Only this service holds the Telegram bot token.

    POST /event              Authorization: Bearer $RELAY_TOKEN
        {"source": "api", "level": "error", "title": "...",
         "detail": "...", "fingerprint": "..."}
    POST /gcp?token=$GCP_WEBHOOK_TOKEN   Cloud Monitoring incident webhook
    GET  /health

Alerts sharing a fingerprint go out at most once per DEDUP_SECONDS; the next
one reports how many repeats were held back. "resolved" always goes out.
Deploy with --max-instances=1 so every caller shares the same dedup state.
"""

from __future__ import annotations

import os
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

TELEGRAM_LIMIT = 4096
_ICONS = {"error": "🔴", "warning": "🟠", "info": "🔵", "resolved": "✅"}

Level = Literal["error", "warning", "info", "resolved"]
Sender = Callable[[str], Awaitable[bool]]


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    relay_token: str = ""
    gcp_webhook_token: str = ""
    dedup_seconds: float = 600
    per_minute: int = 20

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
            relay_token=os.environ.get("RELAY_TOKEN", "").strip(),
            gcp_webhook_token=os.environ.get("GCP_WEBHOOK_TOKEN", "").strip(),
            dedup_seconds=float(os.environ.get("DEDUP_SECONDS", "600")),
        )


@dataclass
class _Seen:
    sent_at: float
    held: int = 0


class Relay:
    """Dedup + rate limit in front of Telegram. State lives in this process."""

    def __init__(
        self,
        *,
        dedup_seconds: float = 600,
        per_minute: int = 20,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.dedup_seconds = dedup_seconds
        self.per_minute = per_minute
        self._clock = clock
        self._seen: dict[str, _Seen] = {}
        self._sent: deque[float] = deque()
        self._dropped = 0

    def admit(self, fingerprint: str | None, level: str) -> tuple[bool, int]:
        """Return (send it?, repeats held back since the last one was sent)."""
        now = self._clock()
        seen = self._seen.get(fingerprint) if fingerprint else None
        if seen and level != "resolved" and now - seen.sent_at < self.dedup_seconds:
            seen.held += 1
            return False, 0
        if not self._take_slot(now):
            self._dropped += 1
            return False, 0
        held = seen.held if seen else 0
        if fingerprint:
            if level == "resolved":
                self._seen.pop(fingerprint, None)
            else:
                self._seen[fingerprint] = _Seen(sent_at=now)
                self._prune(now)
        return True, held

    def take_dropped(self) -> int:
        dropped, self._dropped = self._dropped, 0
        return dropped

    def _take_slot(self, now: float) -> bool:
        while self._sent and now - self._sent[0] >= 60:
            self._sent.popleft()
        if len(self._sent) >= self.per_minute:
            return False
        self._sent.append(now)
        return True

    def _prune(self, now: float) -> None:
        if len(self._seen) < 500:
            return
        cutoff = now - 86_400
        self._seen = {k: v for k, v in self._seen.items() if v.sent_at > cutoff}


def format_message(
    *,
    source: str,
    level: str,
    title: str,
    detail: str = "",
    held: int = 0,
    dropped: int = 0,
) -> str:
    lines = [f"{_ICONS.get(level, _ICONS['error'])} [{source}] {title}".strip()]
    if held:
        lines.append(f"(+{held} more of these since the last alert)")
    if dropped:
        lines.append(f"({dropped} other alerts dropped: more than 20 a minute)")
    if detail:
        lines.append(detail)
    text = "\n".join(lines)
    if len(text) <= TELEGRAM_LIMIT:
        return text
    return text[: TELEGRAM_LIMIT - 1] + "…"


def format_gcp_incident(payload: dict[str, Any]) -> tuple[Level, str, str]:
    """Cloud Monitoring webhook (schema 1.2) -> (level, title, detail)."""
    incident = payload.get("incident") or {}
    labels = (incident.get("resource") or {}).get("labels") or {}
    target = labels.get("host") or incident.get("resource_display_name") or ""
    policy = incident.get("policy_name") or "Cloud Monitoring alert"
    title = f"{policy} — {target}" if target else policy
    detail = "\n".join(p for p in (incident.get("summary"), incident.get("url")) if p)
    if (incident.get("state") or "").lower() == "closed":
        return "resolved", f"Recovered: {title}", detail
    return "error", title, detail


class Event(BaseModel):
    source: str
    level: Level = "error"
    title: str
    detail: str = ""
    fingerprint: str | None = None


def _telegram_sender(config: Config, client: httpx.AsyncClient) -> Sender:
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"

    async def send(text: str) -> bool:
        body = {"chat_id": config.telegram_chat_id, "text": text, "disable_web_page_preview": True}
        try:
            res = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            print(f"telegram send failed: {exc!r}", flush=True)
            return False
        if not res.is_success:
            print(f"telegram send failed: HTTP {res.status_code} {res.text[:300]}", flush=True)
        return res.is_success

    return send


def create_app(config: Config | None = None, send: Sender | None = None) -> FastAPI:
    config = config or Config.from_env()
    relay = Relay(dedup_seconds=config.dedup_seconds, per_minute=config.per_minute)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.send is not None:
            yield
            return
        async with httpx.AsyncClient(timeout=10) as client:
            app.state.send = _telegram_sender(config, client)
            yield

    app = FastAPI(title="Reeltime alert relay", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.send = send

    def check(given: str, expected: str) -> None:
        if not expected:
            raise HTTPException(503, "relay not configured")
        if not secrets.compare_digest(given.encode(), expected.encode()):
            raise HTTPException(401, "bad token")
        if not config.telegram_chat_id:
            raise HTTPException(503, "relay not configured")

    async def deliver(source: str, level: str, title: str, detail: str, fp: str | None) -> dict:
        ok, held = relay.admit(fp, level)
        if not ok:
            return {"sent": False}
        text = format_message(
            source=source,
            level=level,
            title=title,
            detail=detail,
            held=held,
            dropped=relay.take_dropped(),
        )
        if not await app.state.send(text):
            raise HTTPException(502, "telegram send failed")
        print(f"sent {level} alert from {source}: {title[:120]}", flush=True)
        return {"sent": True}

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.post("/event", status_code=202)
    async def event(body: Event, authorization: str = Header(default="")) -> dict:
        check(authorization, f"Bearer {config.relay_token}" if config.relay_token else "")
        return await deliver(body.source, body.level, body.title, body.detail, body.fingerprint)

    @app.post("/gcp", status_code=202)
    async def gcp(payload: dict[str, Any], token: str = Query(default="")) -> dict:
        check(token, config.gcp_webhook_token)
        level, title, detail = format_gcp_incident(payload)
        # GCP already sends one notification per state change: no dedup.
        return await deliver("gcp", level, title, detail, None)

    return app


app = create_app()
