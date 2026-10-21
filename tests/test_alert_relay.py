"""Alert relay (ops/alert_relay): auth, dedup, rate limit, GCP incident format."""

from fastapi.testclient import TestClient

from ops.alert_relay.main import Config, Relay, create_app, format_message

CONFIG = Config(
    telegram_bot_token="bot",
    telegram_chat_id="-100",
    relay_token="relay-secret",
    gcp_webhook_token="gcp-secret",
)
AUTH = {"Authorization": "Bearer relay-secret"}


def _client(sent: list[str], *, ok: bool = True, config: Config = CONFIG) -> TestClient:
    async def send(text: str) -> bool:
        sent.append(text)
        return ok

    return TestClient(create_app(config, send=send))


def test_event_requires_the_relay_token() -> None:
    sent: list[str] = []
    client = _client(sent)
    body = {"source": "api", "title": "boom"}

    assert client.post("/event", json=body).status_code == 401
    assert (
        client.post("/event", json=body, headers={"Authorization": "Bearer no"}).status_code == 401
    )
    assert sent == []


def test_event_is_formatted_and_sent() -> None:
    sent: list[str] = []
    res = _client(sent).post(
        "/event",
        headers=AUTH,
        json={"source": "api", "title": "ValueError: bad", "detail": "GET /movies"},
    )

    assert res.status_code == 202
    assert res.json() == {"sent": True}
    assert sent == ["🔴 [api] ValueError: bad\nGET /movies"]


def test_repeats_are_held_back_then_counted() -> None:
    now = [1000.0]
    relay = Relay(dedup_seconds=600, clock=lambda: now[0])

    assert relay.admit("fp", "error") == (True, 0)
    assert relay.admit("fp", "error") == (False, 0)
    assert relay.admit("fp", "error") == (False, 0)
    now[0] += 601
    assert relay.admit("fp", "error") == (True, 2)


def test_resolved_always_goes_out_and_resets_the_fingerprint() -> None:
    relay = Relay(clock=lambda: 0.0)

    assert relay.admit("disk", "error") == (True, 0)
    assert relay.admit("disk", "error") == (False, 0)
    assert relay.admit("disk", "resolved") == (True, 1)
    assert relay.admit("disk", "error") == (True, 0)


def test_rate_limit_drops_and_reports_the_count() -> None:
    now = [0.0]
    relay = Relay(per_minute=2, clock=lambda: now[0])

    assert relay.admit(None, "error")[0]
    assert relay.admit(None, "error")[0]
    assert relay.admit(None, "error") == (False, 0)
    now[0] = 61
    assert relay.admit(None, "error")[0]
    assert relay.take_dropped() == 1
    assert relay.take_dropped() == 0


def test_long_messages_are_cut_to_the_telegram_limit() -> None:
    text = format_message(source="api", level="error", title="t", detail="x" * 10_000)

    assert len(text) == 4096
    assert text.endswith("…")


def test_gcp_webhook_needs_its_token_and_reports_open_and_closed() -> None:
    sent: list[str] = []
    client = _client(sent)
    incident = {
        "incident": {
            "state": "open",
            "policy_name": "Uptime check failed",
            "resource": {"type": "uptime_url", "labels": {"host": "api.reeltime.fun"}},
            "summary": "An uptime check on api.reeltime.fun is failing.",
            "url": "https://console.cloud.google.com/monitoring/alerting/incidents/1",
        },
        "version": "1.2",
    }

    assert client.post("/gcp", json=incident).status_code == 401
    assert client.post("/gcp?token=gcp-secret", json=incident).status_code == 202
    incident["incident"]["state"] = "closed"
    assert client.post("/gcp?token=gcp-secret", json=incident).status_code == 202

    assert sent[0].startswith("🔴 [gcp] Uptime check failed — api.reeltime.fun\n")
    assert sent[1].startswith("✅ [gcp] Recovered: Uptime check failed — api.reeltime.fun\n")


def test_unconfigured_relay_refuses_requests() -> None:
    sent: list[str] = []
    client = _client(sent, config=Config(relay_token="relay-secret"))

    res = client.post("/event", headers=AUTH, json={"source": "api", "title": "boom"})

    assert res.status_code == 503
    assert sent == []


def test_telegram_failure_is_reported_to_the_caller() -> None:
    sent: list[str] = []
    res = _client(sent, ok=False).post(
        "/event", headers=AUTH, json={"source": "api", "title": "boom"}
    )

    assert res.status_code == 502
