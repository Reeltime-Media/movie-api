"""Anonymous checkout identity — an opaque cookie token standing in for a
user_id so a guest can buy and watch a movie without an account."""

import secrets

from fastapi import Request, Response

from app.config import get_settings

settings = get_settings()

GUEST_COOKIE_NAME = "rt_guest_id"
_GUEST_ID_MAX_AGE = 60 * 60 * 24 * 365 * 2  # 2 years


def _cookie_kwargs() -> dict:
    # Secure cookies are dropped over plain HTTP, so local dev (same-site
    # localhost:3000 <-> localhost:8000) uses Lax without Secure; production
    # (movie-client on Vercel, movie-api on its own domain) is cross-site and
    # needs None+Secure for the cookie to be sent at all.
    if settings.debug:
        return {"secure": False, "samesite": "lax"}
    return {"secure": True, "samesite": "none"}


def get_guest_id(request: Request) -> str | None:
    return request.cookies.get(GUEST_COOKIE_NAME)


def get_or_create_guest_id(request: Request, response: Response) -> str:
    guest_id = get_guest_id(request)
    if guest_id:
        return guest_id
    guest_id = secrets.token_urlsafe(32)
    response.set_cookie(
        key=GUEST_COOKIE_NAME,
        value=guest_id,
        max_age=_GUEST_ID_MAX_AGE,
        path="/",
        httponly=True,
        **_cookie_kwargs(),
    )
    return guest_id


def clear_guest_cookie(response: Response) -> None:
    response.delete_cookie(key=GUEST_COOKIE_NAME, path="/", **_cookie_kwargs())
