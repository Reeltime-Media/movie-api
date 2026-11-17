"""PayPal checkout creation and the webhook route (no database, no network)."""

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.billing import paypal, paypal_intents, paypal_router
from app.dependencies.db import get_db


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeDb:
    """Answers the few queries checkout makes; records what gets added."""

    def __init__(self, *, movie=None, purchased=False, seen_event=False):
        self.movie = movie
        self.purchased = purchased
        self.seen_event = seen_event
        self.added: list = []
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.flush = AsyncMock()
        self.info: dict = {}

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, statement):
        text = str(statement).lower()
        if "from purchases" in text:
            return _Result(uuid.uuid4() if self.purchased else None)
        if "from content" in text:
            return _Result(self.movie)
        if "from webhook_events" in text:
            return _Result(1 if self.seen_event else None)
        return _Result(None)


def _movie(price="2.99"):
    return SimpleNamespace(id=uuid.uuid4(), title="A Movie", price_usd=Decimal(price))


@pytest.fixture
def enabled(settings_factory):
    settings_factory(
        debug=True,
        paypal_client_id="a",
        paypal_client_secret="b",
        paypal_webhook_id="WH-1",
    )


# --- creating a checkout ----------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_charges_the_server_price_and_returns_the_paypal_link(enabled, monkeypatch):
    movie = _movie("3.49")
    db = FakeDb(movie=movie)
    create = AsyncMock(
        return_value={
            "id": "ORDER-7",
            "links": [{"rel": "payer-action", "href": "https://paypal.example/pay"}],
        }
    )
    monkeypatch.setattr(paypal, "create_order", create)

    intent, url = await paypal_intents.create_movie_paypal_intent(
        db,
        content_id=movie.id,
        user=None,
        guest_id="guest-1",
        return_path="/watch/a-movie",
        client="web",
        origin=None,
    )

    assert url == "https://paypal.example/pay"
    assert intent.method == "paypal" and intent.status == "pending"
    assert intent.amount_usd == Decimal("3.49")
    assert intent.paypal_order_id == "ORDER-7"
    assert intent.guest_id == "guest-1" and intent.user_id is None
    sent = create.await_args.kwargs
    assert sent["amount_usd"] == Decimal("3.49")
    assert sent["intent_id"] == intent.intent_id
    assert "next=%2Fwatch%2Fa-movie" in sent["return_url"]


@pytest.mark.asyncio
async def test_owned_movie_is_not_sold_twice(enabled):
    db = FakeDb(movie=_movie(), purchased=True)
    with pytest.raises(HTTPException) as exc:
        await paypal_intents.create_movie_paypal_intent(
            db,
            content_id=uuid.uuid4(),
            user=None,
            guest_id="g",
            return_path=None,
            client="web",
            origin=None,
        )
    assert exc.value.status_code == 409 and db.added == []


@pytest.mark.asyncio
async def test_unknown_or_unpublished_movie_is_404(enabled):
    db = FakeDb(movie=None)
    with pytest.raises(HTTPException) as exc:
        await paypal_intents.create_movie_paypal_intent(
            db,
            content_id=uuid.uuid4(),
            user=None,
            guest_id="g",
            return_path=None,
            client="web",
            origin=None,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_paypal_failure_closes_the_intent_and_is_502(enabled, monkeypatch):
    db = FakeDb(movie=_movie())
    monkeypatch.setattr(
        paypal, "create_order", AsyncMock(side_effect=paypal.PaypalApiError(500, "X", "boom"))
    )
    with pytest.raises(HTTPException) as exc:
        await paypal_intents.create_movie_paypal_intent(
            db,
            content_id=uuid.uuid4(),
            user=None,
            guest_id="g",
            return_path=None,
            client="web",
            origin=None,
        )
    assert exc.value.status_code == 502
    assert db.added[0].status == "failed" and db.added[0].paypal_order_id is None


@pytest.mark.asyncio
async def test_checkout_is_503_while_paypal_is_not_configured(settings_factory):
    settings_factory(debug=True)
    with pytest.raises(HTTPException) as exc:
        await paypal_intents.create_movie_paypal_intent(
            FakeDb(),
            content_id=uuid.uuid4(),
            user=None,
            guest_id="g",
            return_path=None,
            client="web",
            origin=None,
        )
    assert exc.value.status_code == 503


# --- webhook route ----------------------------------------------------------------


def _client(db: FakeDb) -> TestClient:
    app = FastAPI()
    app.include_router(paypal_router.webhook_router)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


_EVENT = {
    "id": "EVT-1",
    "event_type": "PAYMENT.CAPTURE.COMPLETED",
    "resource": {
        "id": "CAP-1",
        "status": "COMPLETED",
        "custom_id": "pp-1",
        "amount": {"currency_code": "USD", "value": "2.99"},
        "payee": {"email_address": "merchant@example.com"},
        "payer": {"email_address": "buyer@example.com", "name": {"given_name": "Bob"}},
    },
}


def test_webhook_is_503_when_not_configured(settings_factory):
    settings_factory(debug=True)
    response = _client(FakeDb()).post("/webhooks/paypal", json=_EVENT)
    assert response.status_code == 503


def test_webhook_with_a_bad_signature_is_rejected_and_nothing_runs(enabled, monkeypatch):
    process = AsyncMock()
    monkeypatch.setattr(paypal, "verify_webhook_signature", AsyncMock(return_value=False))
    monkeypatch.setattr(paypal_router, "process_paypal_event", process)
    response = _client(FakeDb()).post("/webhooks/paypal", json=_EVENT)
    assert response.status_code == 401
    process.assert_not_awaited()


def test_webhook_rejects_non_json(enabled):
    response = _client(FakeDb()).post("/webhooks/paypal", content=b"not json")
    assert response.status_code == 400


def test_verified_webhook_is_processed_once_and_stored_without_payer_details(enabled, monkeypatch):
    db = FakeDb()
    process = AsyncMock(return_value="fulfilled")
    monkeypatch.setattr(paypal, "verify_webhook_signature", AsyncMock(return_value=True))
    monkeypatch.setattr(paypal_router, "process_paypal_event", process)

    response = _client(db).post("/webhooks/paypal", json=_EVENT)

    assert response.status_code == 200 and response.json() == {"status": "ok"}
    process.assert_awaited_once()
    record = db.added[0]
    assert record.provider == "paypal" and record.processed_at is not None
    stored = str(record.payload)
    assert "buyer@example.com" not in stored and "Bob" not in stored
    assert record.payload["resource"]["custom_id"] == "pp-1"
    db.commit.assert_awaited()


def test_redelivered_webhook_is_acknowledged_without_reprocessing(enabled, monkeypatch):
    process = AsyncMock()
    monkeypatch.setattr(paypal, "verify_webhook_signature", AsyncMock(return_value=True))
    monkeypatch.setattr(paypal_router, "process_paypal_event", process)
    response = _client(FakeDb(seen_event=True)).post("/webhooks/paypal", json=_EVENT)
    assert response.json() == {"status": "duplicate"}
    process.assert_not_awaited()


def test_a_failing_event_is_a_5xx_so_paypal_retries(enabled, monkeypatch):
    monkeypatch.setattr(paypal, "verify_webhook_signature", AsyncMock(return_value=True))
    monkeypatch.setattr(
        paypal_router,
        "process_paypal_event",
        AsyncMock(side_effect=HTTPException(status_code=502, detail="PayPal down")),
    )
    response = _client(FakeDb()).post("/webhooks/paypal", json=_EVENT)
    assert response.status_code == 502
