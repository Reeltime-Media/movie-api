"""Sign in with Apple: identity token checks and account matching."""

import asyncio
import hashlib
import time
import uuid
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.exceptions import ConflictError, UnauthorizedError
from app.main import app
from app.models.session import Session
from app.models.user import User
from app.services import auth as auth_service

_CLIENT_ID = "com.reeltimemedia.movieMobile"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _identity_token(raw_nonce="nonce-1", **overrides):
    claims = {
        "iss": "https://appleid.apple.com",
        "aud": _CLIENT_ID,
        "sub": "apple-sub-1",
        "email": "Viewer@Example.com",
        "email_verified": "true",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "nonce": hashlib.sha256(raw_nonce.encode()).hexdigest(),
        **overrides,
    }
    return jwt.encode(claims, _KEY, algorithm="RS256")


@pytest.fixture
def apple_keys(monkeypatch):
    monkeypatch.setattr(auth_service.settings, "apple_client_id", _CLIENT_ID)
    monkeypatch.setattr(
        auth_service,
        "_apple_jwks",
        SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=_KEY.public_key())
        ),
    )


def test_valid_identity_token_returns_its_claims(apple_keys):
    claims = auth_service._verify_apple_identity_token(_identity_token(), "nonce-1")

    assert claims["sub"] == "apple-sub-1"


def test_token_for_another_app_is_rejected(apple_keys):
    with pytest.raises(UnauthorizedError):
        auth_service._verify_apple_identity_token(
            _identity_token(aud="com.example.other"), "nonce-1"
        )


def test_token_from_another_issuer_is_rejected(apple_keys):
    with pytest.raises(UnauthorizedError):
        auth_service._verify_apple_identity_token(
            _identity_token(iss="https://example.com"), "nonce-1"
        )


def test_expired_token_is_rejected(apple_keys):
    with pytest.raises(UnauthorizedError):
        auth_service._verify_apple_identity_token(
            _identity_token(exp=int(time.time()) - 60), "nonce-1"
        )


def test_replayed_token_with_a_different_nonce_is_rejected(apple_keys):
    with pytest.raises(UnauthorizedError):
        auth_service._verify_apple_identity_token(_identity_token(), "nonce-2")


def test_unconfigured_server_rejects_apple_sign_in(monkeypatch):
    monkeypatch.setattr(auth_service.settings, "apple_client_id", "")

    with pytest.raises(UnauthorizedError, match="not configured"):
        auth_service._verify_apple_identity_token("token", "nonce-1")


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _Db:
    def __init__(self, by_apple=None, by_email=None):
        self.results = [by_apple, by_email]
        self.added = []

    async def execute(self, _stmt):
        return _Result(self.results.pop(0) if self.results else None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if isinstance(obj, User) and obj.id is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        pass

    async def refresh(self, _obj):
        pass


@pytest.fixture
def signed_in(monkeypatch):
    async def _claim(*_a, **_k):
        return None

    async def _session(_db, _user_id, _ua):
        return Session(id=uuid.uuid4())

    monkeypatch.setattr(auth_service, "claim_guest_purchases", _claim)
    monkeypatch.setattr(auth_service, "create_session", _session)


def _claims(monkeypatch, **claims):
    monkeypatch.setattr(auth_service, "_verify_apple_identity_token", lambda _token, _nonce: claims)


def _authenticate(db, full_name=None):
    return asyncio.run(auth_service.authenticate_apple(db, "token", "nonce-1", full_name=full_name))


def test_first_sign_in_creates_an_active_account(monkeypatch, signed_in):
    _claims(monkeypatch, sub="apple-1", email="Viewer@Example.com", email_verified="true")
    db = _Db()

    user, token = _authenticate(db, full_name="A Viewer")

    assert user.apple_id == "apple-1"
    assert user.email == "viewer@example.com"
    assert user.full_name == "A Viewer"
    assert user.is_active is True
    assert token


def test_returning_user_signs_in_without_an_email_claim(monkeypatch, signed_in):
    existing = User(
        id=uuid.uuid4(), email="v@example.com", apple_id="apple-1", role="user", is_active=True
    )
    _claims(monkeypatch, sub="apple-1")

    user, _ = _authenticate(_Db(by_apple=existing))

    assert user is existing


def test_verified_email_links_an_existing_account(monkeypatch, signed_in):
    existing = User(id=uuid.uuid4(), email="v@example.com", role="user", is_active=True)
    _claims(monkeypatch, sub="apple-1", email="v@example.com", email_verified=True)

    user, _ = _authenticate(_Db(by_email=existing))

    assert user is existing
    assert user.apple_id == "apple-1"


def test_email_linked_to_a_different_apple_id_conflicts(monkeypatch, signed_in):
    existing = User(
        id=uuid.uuid4(), email="v@example.com", apple_id="apple-2", role="user", is_active=True
    )
    _claims(monkeypatch, sub="apple-1", email="v@example.com", email_verified="true")

    with pytest.raises(ConflictError):
        _authenticate(_Db(by_email=existing))


def test_unverified_email_cannot_create_or_link_an_account(monkeypatch, signed_in):
    _claims(monkeypatch, sub="apple-1", email="v@example.com", email_verified="false")

    with pytest.raises(UnauthorizedError, match="not verified"):
        _authenticate(_Db())


def test_unknown_user_without_email_is_rejected(monkeypatch, signed_in):
    _claims(monkeypatch, sub="apple-1")

    with pytest.raises(UnauthorizedError):
        _authenticate(_Db())


def test_disabled_account_is_rejected(monkeypatch, signed_in):
    existing = User(
        id=uuid.uuid4(), email="v@example.com", apple_id="apple-1", role="user", is_active=False
    )
    _claims(monkeypatch, sub="apple-1")

    with pytest.raises(UnauthorizedError, match="disabled"):
        _authenticate(_Db(by_apple=existing))


def test_apple_route_is_registered():
    assert "post" in app.openapi()["paths"]["/auth/apple"]
