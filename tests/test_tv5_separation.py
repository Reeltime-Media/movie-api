"""TV5 and Reeltime share accounts but not catalogs or subscriptions."""

import asyncio
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.billing import fulfillment
from app.billing.intents import _same_plan_intent
from app.models.content import Content
from app.models.user import User
from app.schemas.admin import AdminMovieCreate
from app.schemas.match import MatchDetailsWrite
from app.services import content_access


class FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class FakeDb:
    """Answers each query in turn and keeps the SQL it was asked."""

    def __init__(self, results):
        self._results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0)


def title(app, *, free=False, price=None, kind="single"):
    return Content(
        id=uuid.uuid4(),
        type=kind,
        app=app,
        slug="t",
        title="T",
        is_published=True,
        is_free=free,
        price_usd=price,
        series_id=uuid.uuid4() if kind == "episode" else None,
    )


def viewer():
    return User(id=uuid.uuid4(), email="v@x.io", role="user")


def can_watch(db, user, content):
    return asyncio.run(content_access.can_access_content(db, user, None, content))


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect()))


def test_unpriced_tv5_match_is_not_free():
    # Reeltime treats an unpriced movie as free; TV5 must not.
    assert can_watch(FakeDb([FakeResult(None)]), viewer(), title("tv5")) is False


def test_guest_cannot_watch_a_paid_tv5_title():
    assert can_watch(FakeDb([]), None, title("tv5")) is False


@pytest.mark.parametrize("kind", ["single", "episode"])
def test_tv5_subscription_unlocks_tv5_titles(kind):
    db = FakeDb([FakeResult(object())])

    assert can_watch(db, viewer(), title("tv5", kind=kind)) is True
    assert "subscriptions.app" in sql(db.statements[0])


def test_tv5_access_asks_for_the_tv5_subscription_only():
    db = FakeDb([FakeResult(None)])
    can_watch(db, viewer(), title("tv5"))

    compiled = db.statements[0].compile(dialect=postgresql.dialect())
    assert "tv5" in compiled.params.values()
    assert "reeltime" not in compiled.params.values()


def test_free_tv5_title_is_open_to_guests():
    assert can_watch(FakeDb([]), None, title("tv5", free=True)) is True


def test_reeltime_subscription_check_asks_for_reeltime():
    db = FakeDb([FakeResult(None)])
    asyncio.run(content_access.user_has_active_subscription(db, uuid.uuid4()))

    assert "reeltime" in db.statements[0].compile(dialect=postgresql.dialect()).params.values()


def test_unsaved_reeltime_title_is_still_treated_as_reeltime():
    unsaved = title(None, price=Decimal("0"))

    assert can_watch(FakeDb([]), viewer(), unsaved) is True


def test_tv5_plans_never_reuse_a_legacy_intent_on_price():
    clause = sql(_same_plan_intent("tv5_monthly", "tv5", Decimal("3.99")))

    assert "plan_code IS NULL" not in clause


def test_reeltime_plans_still_reuse_legacy_intents():
    clause = sql(_same_plan_intent("monthly", "reeltime", Decimal("3.99")))

    assert "plan_code IS NULL" in clause


def test_switched_off_tv5_plan_is_still_what_was_paid_for(monkeypatch):
    tv5_plan = SimpleNamespace(code="tv5_monthly", app="tv5", is_active=False)

    async def by_code(_db, code):
        return tv5_plan if code == "tv5_monthly" else None

    monkeypatch.setattr(fulfillment, "get_subscription_plan_by_code", by_code)
    intent = SimpleNamespace(plan_code="tv5_monthly", order_id="sub-tv5_monthly-abc")

    assert asyncio.run(fulfillment._resolve_plan_for_subscription_intent(None, intent)) is tv5_plan


def test_legacy_intents_only_match_reeltime_plans_by_price(monkeypatch):
    asked = {}

    async def plans(_db, *, active_only, app, audience=None):
        asked["app"] = app
        asked["audience"] = audience
        return [SimpleNamespace(code="monthly", app="reeltime", price_usd=Decimal("3.99"))]

    monkeypatch.setattr(fulfillment, "list_subscription_plans", plans)
    intent = SimpleNamespace(plan_code=None, order_id="legacy-1", amount_usd=Decimal("3.99"))

    plan = asyncio.run(fulfillment._resolve_plan_for_subscription_intent(None, intent))

    assert asked["app"] == "reeltime"
    assert plan.code == "monthly"


def fight_card(**extra):
    return {"red_fighter": "Moeun Sokhuch", "blue_fighter": "Ahmad Masouminia", **extra}


def test_tv5_title_needs_a_fight_card():
    with pytest.raises(ValidationError, match="both fighters"):
        AdminMovieCreate(title="Bout", app="tv5")


def test_reeltime_movie_cannot_have_a_fight_card():
    with pytest.raises(ValidationError, match="Only TV5"):
        AdminMovieCreate(title="Movie", match=fight_card())


def test_fight_card_tidies_names_and_blanks():
    card = MatchDetailsWrite(**fight_card(red_fighter="  Moeun   Sokhuch ", event_name="  "))

    assert card.red_fighter == "Moeun Sokhuch"
    assert card.event_name is None


@pytest.mark.parametrize(
    "bad",
    [{"red_fighter": "   "}, {"winner": "knockout"}, {"result_round": 0}],
)
def test_fight_card_rejects_bad_values(bad):
    with pytest.raises(ValidationError):
        MatchDetailsWrite(**fight_card(**bad))


def test_unknown_app_is_rejected():
    with pytest.raises(ValidationError):
        AdminMovieCreate(title="Movie", app="netflix")


def test_paypal_never_sells_a_tv5_series(settings_factory):
    from app.billing import paypal_intents
    from app.core.exceptions import NotFoundError

    settings_factory(debug=True, paypal_client_id="a", paypal_client_secret="b")
    series = SimpleNamespace(id=uuid.uuid4(), app="tv5", title="S")
    with pytest.raises(NotFoundError):
        asyncio.run(
            paypal_intents.create_series_paypal_intent(
                FakeDb([]),
                series=series,
                user=None,
                guest_id="g",
                return_path=None,
                client="web",
                origin=None,
            )
        )


def test_paypal_only_looks_up_reeltime_movies(settings_factory):
    from app.billing import paypal_intents
    from app.core.exceptions import NotFoundError

    settings_factory(debug=True, paypal_client_id="a", paypal_client_secret="b")
    db = FakeDb([FakeResult(None), FakeResult(None)])
    with pytest.raises(NotFoundError):
        asyncio.run(
            paypal_intents.create_movie_paypal_intent(
                db,
                content_id=uuid.uuid4(),
                user=None,
                guest_id="g",
                return_path=None,
                client="web",
                origin=None,
            )
        )
    params = db.statements[1].compile(dialect=postgresql.dialect()).params.values()
    assert "reeltime" in params


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeListResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return FakeScalars(self._rows)


@pytest.mark.parametrize("app", ["reeltime", "tv5"])
def test_my_subscriptions_lists_one_app_only(app):
    from app.routers.subscriptions import get_my_subscriptions

    db = FakeDb([FakeListResult([])])
    asyncio.run(get_my_subscriptions(db, viewer(), app=app))
    statement = db.statements[0]
    assert "subscriptions.app" in sql(statement)
    assert app in statement.compile(dialect=postgresql.dialect()).params.values()


def test_my_subscriptions_default_to_reeltime():
    """Older Reeltime apps call /subscriptions/me with no query and must never get a
    TV5 subscription back (they'd treat it as a Reeltime one)."""
    import inspect

    from app.routers.subscriptions import get_my_subscriptions

    default = inspect.signature(get_my_subscriptions).parameters["app"].default
    assert default.default == "reeltime"
