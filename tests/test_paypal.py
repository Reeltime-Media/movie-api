"""PayPal client: token handling, order payload, URLs, capture checks, webhook verify."""

import base64
import json
from decimal import Decimal

import httpx
import pytest

from app.billing import paypal


@pytest.fixture
def configured(settings_factory):
    settings_factory(
        debug=True,
        paypal_client_id="client-id",
        paypal_client_secret="client-secret",
        paypal_mode="sandbox",
        paypal_webhook_id="WH-123",
        cors_origins="https://shop.example",
    )


@pytest.fixture
def mock_paypal(configured):
    """Install an httpx client whose requests are answered by a handler; yields the log."""
    calls: list[httpx.Request] = []
    handlers: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        key = f"{request.method} {request.url.path}"
        result = handlers.get(key)
        if result is None:
            return httpx.Response(404, json={"name": "NOT_FOUND"})
        return result(request) if callable(result) else result

    handlers["POST /v1/oauth2/token"] = httpx.Response(
        200, json={"access_token": "tok-1", "expires_in": 32400}
    )
    paypal.set_client_for_tests(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    yield calls, handlers
    paypal.set_client_for_tests(None)


# --- settings ---------------------------------------------------------------------


def test_paypal_is_off_without_credentials(settings_factory):
    s = settings_factory(debug=True)
    assert s.paypal_enabled is False


def test_paypal_needs_both_id_and_secret(settings_factory):
    with pytest.raises(ValueError, match="set together"):
        settings_factory(debug=True, paypal_client_id="only-id")


def test_paypal_mode_must_be_known(settings_factory):
    with pytest.raises(ValueError, match="PAYPAL_MODE"):
        settings_factory(debug=True, paypal_mode="production")


def test_live_mode_uses_the_live_api(settings_factory):
    s = settings_factory(
        debug=True, paypal_client_id="a", paypal_client_secret="b", paypal_mode="live"
    )
    assert s.paypal_api_base == "https://api-m.paypal.com"
    sandbox = settings_factory(debug=True, paypal_mode="sandbox")
    assert sandbox.paypal_api_base == "https://api-m.sandbox.paypal.com"


def test_production_requires_the_webhook_id(settings_factory):
    with pytest.raises(ValueError, match="PAYPAL_WEBHOOK_ID"):
        settings_factory(
            debug=False,
            paypal_client_id="a",
            paypal_client_secret="b",
            database_ssl_allow_insecure="true",
        )


# --- return urls ------------------------------------------------------------------


def test_safe_return_path_only_allows_same_site_paths():
    assert paypal.safe_return_path("/watch/movie?x=1") == "/watch/movie?x=1"
    for bad in ("//evil.example", "https://evil.example", "javascript:alert(1)", "/a\\b", "/x\ny"):
        assert paypal.safe_return_path(bad) is None
    assert paypal.safe_return_path("/" + "a" * 400) is None
    assert paypal.safe_return_path(None) is None


def test_return_origin_is_only_honoured_when_allow_listed(configured):
    ok, _ = paypal.build_return_urls("pp-1", "/watch/x", "web", "https://shop.example")
    assert ok.startswith("https://shop.example/pay/paypal/return?")
    bad, _ = paypal.build_return_urls("pp-1", "/watch/x", "web", "https://evil.example")
    assert not bad.startswith("https://evil.example")


def test_cancel_url_marks_cancelled(configured):
    ret, cancel = paypal.build_return_urls("pp-1", None, "app", None)
    assert "cancelled=1" not in ret and cancel.endswith("&cancelled=1")
    assert "intent=pp-1" in ret and "client=app" in ret


# --- capture checks ---------------------------------------------------------------


def _capture(value="2.99", currency="USD", custom_id="pp-1"):
    return {
        "id": "CAP-1",
        "status": "COMPLETED",
        "custom_id": custom_id,
        "amount": {"currency_code": currency, "value": value},
    }


def test_capture_must_match_amount_currency_and_intent():
    amount = Decimal("2.99")
    assert paypal.capture_matches(_capture(), intent_id="pp-1", amount_usd=amount)
    assert not paypal.capture_matches(_capture(value="0.01"), intent_id="pp-1", amount_usd=amount)
    assert not paypal.capture_matches(_capture(currency="EUR"), intent_id="pp-1", amount_usd=amount)
    assert not paypal.capture_matches(
        _capture(custom_id="pp-other"), intent_id="pp-1", amount_usd=amount
    )
    assert not paypal.capture_matches(_capture(value="abc"), intent_id="pp-1", amount_usd=amount)
    assert not paypal.capture_matches({}, intent_id="pp-1", amount_usd=amount)


# --- API calls --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_sends_server_price_and_binds_intent(mock_paypal):
    calls, handlers = mock_paypal
    handlers["POST /v2/checkout/orders"] = httpx.Response(
        201,
        json={
            "id": "ORDER-1",
            "status": "PAYER_ACTION_REQUIRED",
            "links": [
                {"rel": "self", "href": "https://api/self"},
                {
                    "rel": "payer-action",
                    "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-1",
                },
            ],
        },
    )
    order = await paypal.create_order(
        intent_id="pp-1",
        order_id="movie-abc",
        amount_usd=Decimal("2.9"),
        description="REELTIME - A Movie",
        return_url="https://shop.example/pay/paypal/return?intent=pp-1",
        cancel_url="https://shop.example/pay/paypal/return?intent=pp-1&cancelled=1",
    )

    token_call, order_call = calls
    expected_basic = base64.b64encode(b"client-id:client-secret").decode()
    assert token_call.headers["authorization"] == f"Basic {expected_basic}"
    assert order_call.url.host == "api-m.sandbox.paypal.com"
    assert order_call.headers["authorization"] == "Bearer tok-1"
    assert order_call.headers["paypal-request-id"] == "create-pp-1"
    body = json.loads(order_call.content)
    unit = body["purchase_units"][0]
    assert body["intent"] == "CAPTURE"
    assert unit["amount"] == {"currency_code": "USD", "value": "2.90"}
    assert unit["custom_id"] == "pp-1" and unit["invoice_id"] == "movie-abc"
    ctx = body["payment_source"]["paypal"]["experience_context"]
    assert ctx["return_url"].endswith("intent=pp-1") and ctx["user_action"] == "PAY_NOW"
    assert paypal.approve_url(order).endswith("token=ORDER-1")


@pytest.mark.asyncio
async def test_access_token_is_reused(mock_paypal):
    calls, handlers = mock_paypal
    handlers["GET /v2/checkout/orders/ORDER-1"] = httpx.Response(200, json={"id": "ORDER-1"})
    await paypal.get_order("ORDER-1")
    await paypal.get_order("ORDER-1")
    assert [c.url.path for c in calls].count("/v1/oauth2/token") == 1


@pytest.mark.asyncio
async def test_paypal_errors_carry_the_issue_code(mock_paypal):
    _, handlers = mock_paypal
    handlers["POST /v2/checkout/orders/ORDER-1/capture"] = httpx.Response(
        422,
        json={
            "name": "UNPROCESSABLE_ENTITY",
            "details": [{"issue": "ORDER_NOT_APPROVED", "description": "nope"}],
        },
    )
    with pytest.raises(paypal.PaypalApiError) as exc:
        await paypal.capture_order("ORDER-1", intent_id="pp-1")
    assert exc.value.issue == "ORDER_NOT_APPROVED" and exc.value.status_code == 422


@pytest.mark.asyncio
async def test_calls_fail_cleanly_when_not_configured(settings_factory):
    settings_factory(debug=True)
    paypal.set_client_for_tests(None)
    with pytest.raises(paypal.PaypalNotConfiguredError):
        await paypal.get_order("ORDER-1")


# --- webhook signature ------------------------------------------------------------

_HEADERS = {
    "paypal-auth-algo": "SHA256withRSA",
    "paypal-cert-url": "https://api.paypal.com/cert.pem",
    "paypal-transmission-id": "tx-1",
    "paypal-transmission-sig": "sig",
    "paypal-transmission-time": "2026-11-17T01:00:00Z",
}


@pytest.mark.asyncio
async def test_webhook_signature_success_sends_our_webhook_id(mock_paypal):
    calls, handlers = mock_paypal
    handlers["POST /v1/notifications/verify-webhook-signature"] = httpx.Response(
        200, json={"verification_status": "SUCCESS"}
    )
    event = {"id": "WH-EVT-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"}
    assert await paypal.verify_webhook_signature(_HEADERS, event) is True
    sent = json.loads(calls[-1].content)
    assert sent["webhook_id"] == "WH-123" and sent["webhook_event"] == event
    assert sent["transmission_id"] == "tx-1"


@pytest.mark.asyncio
async def test_webhook_signature_failure_and_missing_headers(mock_paypal):
    _, handlers = mock_paypal
    handlers["POST /v1/notifications/verify-webhook-signature"] = httpx.Response(
        200, json={"verification_status": "FAILURE"}
    )
    assert await paypal.verify_webhook_signature(_HEADERS, {"id": "x"}) is False
    assert await paypal.verify_webhook_signature({}, {"id": "x"}) is False


@pytest.mark.asyncio
async def test_webhook_is_rejected_when_paypal_cannot_be_asked(mock_paypal):
    _, handlers = mock_paypal
    handlers["POST /v1/notifications/verify-webhook-signature"] = httpx.Response(500)
    assert await paypal.verify_webhook_signature(_HEADERS, {"id": "x"}) is False


@pytest.mark.asyncio
async def test_webhook_is_rejected_without_a_webhook_id(settings_factory):
    settings_factory(debug=True, paypal_client_id="a", paypal_client_secret="b")
    assert await paypal.verify_webhook_signature(_HEADERS, {"id": "x"}) is False


# --- card-first hint (buyers without a PayPal account) -----------------------------


def _order_kwargs(**extra):
    return {
        "intent_id": "pp-1",
        "order_id": "movie-abc",
        "amount_usd": Decimal("2.99"),
        "description": "REELTIME - A Movie",
        "return_url": "https://shop.example/pay/paypal/return?intent=pp-1",
        "cancel_url": "https://shop.example/pay/paypal/return?intent=pp-1&cancelled=1",
        **extra,
    }


def _created(request):
    return httpx.Response(
        201,
        json={"id": "ORDER-1", "links": [{"rel": "payer-action", "href": "https://paypal.com/x"}]},
    )


def test_payload_has_no_landing_page_by_default():
    payload = paypal.order_payload(**_order_kwargs())
    assert "landing_page" not in payload["payment_source"]["paypal"]["experience_context"]


def test_payload_can_ask_for_the_card_page():
    payload = paypal.order_payload(**_order_kwargs(), landing_page=paypal.CARD_LANDING_PAGE)
    context = payload["payment_source"]["paypal"]["experience_context"]
    assert context["landing_page"] == "GUEST_CHECKOUT"


@pytest.mark.asyncio
async def test_card_first_order_asks_paypal_for_the_card_page(mock_paypal):
    calls, handlers = mock_paypal
    handlers["POST /v2/checkout/orders"] = _created
    order = await paypal.create_order(**_order_kwargs(), card_first=True)

    assert order["id"] == "ORDER-1"
    order_calls = [c for c in calls if c.url.path == "/v2/checkout/orders"]
    assert len(order_calls) == 1
    body = json.loads(order_calls[0].content)
    assert (
        body["payment_source"]["paypal"]["experience_context"]["landing_page"] == "GUEST_CHECKOUT"
    )
    assert order_calls[0].headers["paypal-request-id"] == "create-pp-1-card"


@pytest.mark.asyncio
async def test_rejected_card_hint_falls_back_to_a_normal_order(mock_paypal):
    calls, handlers = mock_paypal
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if "landing_page" in body["payment_source"]["paypal"]["experience_context"]:
            return httpx.Response(
                422,
                json={
                    "name": "UNPROCESSABLE_ENTITY",
                    "details": [{"issue": "INVALID_ENUM_VALUE", "description": "bad"}],
                },
            )
        return _created(request)

    handlers["POST /v2/checkout/orders"] = handler
    order = await paypal.create_order(**_order_kwargs(), card_first=True)

    assert order["id"] == "ORDER-1"
    assert len(seen) == 2
    assert "landing_page" in seen[0]["payment_source"]["paypal"]["experience_context"]
    assert "landing_page" not in seen[1]["payment_source"]["paypal"]["experience_context"]
    order_calls = [c for c in calls if c.url.path == "/v2/checkout/orders"]
    assert order_calls[1].headers["paypal-request-id"] == "create-pp-1"


@pytest.mark.asyncio
async def test_a_paypal_outage_is_not_retried_as_a_normal_order(mock_paypal):
    calls, handlers = mock_paypal
    handlers["POST /v2/checkout/orders"] = httpx.Response(
        500, json={"name": "INTERNAL_SERVICE_ERROR"}
    )
    with pytest.raises(paypal.PaypalApiError):
        await paypal.create_order(**_order_kwargs(), card_first=True)
    assert len([c for c in calls if c.url.path == "/v2/checkout/orders"]) == 1


@pytest.mark.asyncio
async def test_normal_order_without_the_hint_is_unchanged(mock_paypal):
    calls, handlers = mock_paypal
    handlers["POST /v2/checkout/orders"] = _created
    await paypal.create_order(**_order_kwargs())
    order_calls = [c for c in calls if c.url.path == "/v2/checkout/orders"]
    assert len(order_calls) == 1
    assert order_calls[0].headers["paypal-request-id"] == "create-pp-1"
