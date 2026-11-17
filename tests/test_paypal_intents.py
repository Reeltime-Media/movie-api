"""PayPal capture / webhook rules: no double charge, no unlock on a wrong amount."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.billing import paypal, paypal_intents
from app.core.exceptions import ConflictError, NotFoundError


def _intent(**overrides):
    base = {
        "intent_id": "pp-1",
        "order_id": "movie-abc",
        "method": "paypal",
        "status": "pending",
        "amount_usd": Decimal("2.99"),
        "paypal_order_id": "ORDER-1",
        "paypal_capture_id": None,
        "resolved_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _order(status="COMPLETED", value="2.99", currency="USD", custom_id="pp-1"):
    return {
        "id": "ORDER-1",
        "status": "COMPLETED",
        "purchase_units": [
            {
                "payments": {
                    "captures": [
                        {
                            "id": "CAP-1",
                            "status": status,
                            "custom_id": custom_id,
                            "amount": {"currency_code": currency, "value": value},
                        }
                    ]
                }
            }
        ],
    }


@pytest.fixture
def env(monkeypatch, settings_factory):
    settings_factory(debug=True, paypal_client_id="a", paypal_client_secret="b")
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock(), flush=AsyncMock(), info={})
    intent = _intent()
    ns = SimpleNamespace(
        db=db,
        intent=intent,
        fulfill=AsyncMock(),
        capture=AsyncMock(return_value=_order()),
        get_order=AsyncMock(return_value=_order()),
        owned=AsyncMock(return_value=False),
    )

    async def find(_db, _order_id):
        if ns.intent is None:
            raise NotFoundError("Payment not found")
        return ns.intent

    monkeypatch.setattr(paypal_intents, "_intent_by_paypal_order", find)
    monkeypatch.setattr(paypal_intents, "fulfill_payment_intent", ns.fulfill)
    monkeypatch.setattr(paypal_intents, "commit_with_telegram", AsyncMock())
    monkeypatch.setattr(paypal_intents, "mark_succeeded_if_already_purchased", ns.owned)
    monkeypatch.setattr(paypal, "capture_order", ns.capture)
    monkeypatch.setattr(paypal, "get_order", ns.get_order)
    return ns


@pytest.mark.asyncio
async def test_matching_capture_unlocks_once(env):
    result = await paypal_intents.capture_paypal_order(env.db, "ORDER-1")
    env.capture.assert_awaited_once_with("ORDER-1", intent_id="pp-1")
    env.fulfill.assert_awaited_once()
    assert env.fulfill.await_args.kwargs["bank"] == "paypal"
    assert result.paypal_capture_id == "CAP-1"


@pytest.mark.asyncio
async def test_wrong_amount_is_never_unlocked(env):
    env.capture.return_value = _order(value="0.50")
    result = await paypal_intents.capture_paypal_order(env.db, "ORDER-1")
    env.fulfill.assert_not_awaited()
    assert result.status == "failed"
    # ops are told, so the money can be refunded by hand
    assert any("MISMATCH" in text for text in env.db.info["pending_telegram_alerts"])


@pytest.mark.asyncio
async def test_other_currency_or_other_intent_is_never_unlocked(env):
    env.capture.return_value = _order(currency="EUR")
    await paypal_intents.capture_paypal_order(env.db, "ORDER-1")
    env.intent.status = "pending"
    env.capture.return_value = _order(custom_id="pp-someone-else")
    await paypal_intents.capture_paypal_order(env.db, "ORDER-1")
    env.fulfill.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_paid_intent_does_not_call_paypal_again(env):
    env.intent.status = "succeeded"
    result = await paypal_intents.capture_paypal_order(env.db, "ORDER-1")
    env.capture.assert_not_awaited()
    assert result.status == "succeeded"


@pytest.mark.asyncio
async def test_buyer_who_already_owns_the_title_is_not_charged(env):
    async def own(_db, intent):
        intent.status = "superseded"
        return True

    env.owned.side_effect = own
    result = await paypal_intents.capture_paypal_order(env.db, "ORDER-1")
    env.capture.assert_not_awaited()
    env.fulfill.assert_not_awaited()
    assert result.status == "superseded"


@pytest.mark.asyncio
async def test_closed_intent_cannot_be_captured(env):
    env.intent.status = "failed"
    with pytest.raises(ConflictError):
        await paypal_intents.capture_paypal_order(env.db, "ORDER-1")
    env.capture.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_order_is_404(env):
    env.intent = None
    with pytest.raises(NotFoundError):
        await paypal_intents.capture_paypal_order(env.db, "NOPE")


@pytest.mark.asyncio
async def test_pending_capture_waits_for_the_webhook(env):
    env.capture.return_value = _order(status="PENDING")
    result = await paypal_intents.capture_paypal_order(env.db, "ORDER-1")
    env.fulfill.assert_not_awaited()
    assert result.status == "pending" and result.paypal_capture_id == "CAP-1"


@pytest.mark.asyncio
async def test_declined_capture_fails_the_intent(env):
    env.capture.return_value = _order(status="DECLINED")
    result = await paypal_intents.capture_paypal_order(env.db, "ORDER-1")
    env.fulfill.assert_not_awaited()
    assert result.status == "failed"


@pytest.mark.asyncio
async def test_already_captured_order_is_read_back_not_recaptured(env):
    env.capture.side_effect = paypal.PaypalApiError(422, "ORDER_ALREADY_CAPTURED", "done")
    result = await paypal_intents.capture_paypal_order(env.db, "ORDER-1")
    env.get_order.assert_awaited_once_with("ORDER-1")
    env.fulfill.assert_awaited_once()
    assert result.paypal_capture_id == "CAP-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("issue", ["ORDER_NOT_APPROVED", "INSTRUMENT_DECLINED"])
async def test_buyer_side_problems_are_409_not_502(env, issue):
    env.capture.side_effect = paypal.PaypalApiError(422, issue, "x")
    with pytest.raises(ConflictError):
        await paypal_intents.capture_paypal_order(env.db, "ORDER-1")
    env.fulfill.assert_not_awaited()


@pytest.mark.asyncio
async def test_paypal_outage_is_502_and_leaves_the_intent_open(env):
    env.capture.side_effect = paypal.PaypalApiError(500, "INTERNAL_SERVICE_ERROR", "x")
    with pytest.raises(HTTPException) as exc:
        await paypal_intents.capture_paypal_order(env.db, "ORDER-1")
    assert exc.value.status_code == 502
    assert env.intent.status == "pending"


@pytest.mark.asyncio
async def test_disabled_paypal_is_503(settings_factory):
    settings_factory(debug=True)
    with pytest.raises(HTTPException) as exc:
        await paypal_intents.capture_paypal_order(SimpleNamespace(), "ORDER-1")
    assert exc.value.status_code == 503


# --- webhook events ---------------------------------------------------------------


def _capture_event(event_type="PAYMENT.CAPTURE.COMPLETED", **resource):
    base = {
        "id": "CAP-9",
        "custom_id": "pp-1",
        "amount": {"currency_code": "USD", "value": "2.99"},
    }
    base.update(resource)
    return {"id": "EVT-1", "event_type": event_type, "resource": base}


@pytest.fixture
def webhook_env(env, monkeypatch):
    async def by_event(_db, _resource):
        return env.intent

    monkeypatch.setattr(paypal_intents, "_intent_for_capture_event", by_event)
    return env


@pytest.mark.asyncio
async def test_order_approved_event_captures_the_order(env):
    outcome = await paypal_intents.process_paypal_event(
        env.db, {"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "ORDER-1"}}
    )
    env.capture.assert_awaited_once()
    env.fulfill.assert_awaited_once()
    # fulfil is mocked here, so the intent object itself stays "pending"
    assert outcome == "capture -> pending"


@pytest.mark.asyncio
async def test_order_approved_for_unknown_order_is_ignored(env):
    env.intent = None
    outcome = await paypal_intents.process_paypal_event(
        env.db, {"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "OTHER"}}
    )
    assert outcome == "ignored: unknown order"


@pytest.mark.asyncio
async def test_capture_completed_event_fulfils(webhook_env):
    outcome = await paypal_intents.process_paypal_event(webhook_env.db, _capture_event())
    assert outcome == "fulfilled"
    webhook_env.fulfill.assert_awaited_once()
    assert webhook_env.intent.paypal_capture_id == "CAP-9"


@pytest.mark.asyncio
async def test_capture_completed_for_paid_intent_is_a_noop(webhook_env):
    webhook_env.intent.status = "succeeded"
    outcome = await paypal_intents.process_paypal_event(webhook_env.db, _capture_event())
    assert outcome == "already fulfilled"
    webhook_env.fulfill.assert_not_awaited()


@pytest.mark.asyncio
async def test_capture_completed_with_wrong_amount_alerts_and_does_not_unlock(webhook_env):
    event = _capture_event(amount={"currency_code": "USD", "value": "0.01"})
    outcome = await paypal_intents.process_paypal_event(webhook_env.db, event)
    assert outcome == "mismatch"
    webhook_env.fulfill.assert_not_awaited()
    assert any("MISMATCH" in t for t in webhook_env.db.info["pending_telegram_alerts"])


@pytest.mark.asyncio
async def test_denied_capture_fails_a_pending_intent(webhook_env):
    outcome = await paypal_intents.process_paypal_event(
        webhook_env.db, _capture_event("PAYMENT.CAPTURE.DENIED")
    )
    assert outcome == "marked failed" and webhook_env.intent.status == "failed"


@pytest.mark.asyncio
async def test_refund_only_alerts_and_keeps_access(webhook_env):
    webhook_env.intent.status = "succeeded"
    outcome = await paypal_intents.process_paypal_event(
        webhook_env.db, _capture_event("PAYMENT.CAPTURE.REFUNDED")
    )
    assert outcome == "alerted" and webhook_env.intent.status == "succeeded"
    assert any("refunded" in t for t in webhook_env.db.info["pending_telegram_alerts"])


@pytest.mark.asyncio
async def test_unknown_event_types_are_ignored(env):
    outcome = await paypal_intents.process_paypal_event(
        env.db, {"event_type": "BILLING.PLAN.CREATED", "resource": {}}
    )
    assert outcome.startswith("ignored")
