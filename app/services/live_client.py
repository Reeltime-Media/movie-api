"""Server-side proxy to the live TV restream service (keeps its API key off
the browser).

Contract expected of LIVE_SERVICE_URL (a separate service, not this repo):
  POST /channels/{channel_id}/start  {"source_url": "..."}
      -> {"status": "starting"|"live", "hls_url": "https://.../index.m3u8"}
  POST /channels/{channel_id}/stop
      -> {"status": "offline"}
  GET  /channels/{channel_id}/status
      -> {"status": "offline"|"starting"|"live"|"error", "hls_url": str|None,
          "error": str|None}

The service owns FFmpeg (pulling the source .m3u8 and writing HLS segments
directly to its origin server); this API only starts/stops/polls it per
channel.
"""

import httpx
from fastapi import HTTPException, status

from app.config import get_settings

_CLIENT_TIMEOUT_SECONDS = 15
_live_client: httpx.AsyncClient | None = None


def _headers() -> dict[str, str]:
    settings = get_settings()
    headers: dict[str, str] = {"Accept": "application/json"}
    if settings.live_service_api_key:
        headers["X-Api-Key"] = settings.live_service_api_key
    return headers


def _base_url() -> str:
    settings = get_settings()
    if not settings.live_service_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Live TV service is not configured",
        )
    return settings.live_service_url.rstrip("/")


def _get_live_client() -> httpx.AsyncClient:
    global _live_client
    if _live_client is None:
        _live_client = httpx.AsyncClient(timeout=_CLIENT_TIMEOUT_SECONDS)
    return _live_client


async def close_http_client() -> None:
    global _live_client
    if _live_client is not None:
        await _live_client.aclose()
        _live_client = None


def _error_detail(exc: httpx.HTTPStatusError, fallback: str) -> str:
    try:
        body = exc.response.json()
        if isinstance(body, dict) and isinstance(body.get("detail"), str):
            return body["detail"]
    except ValueError:
        pass
    return fallback


async def start_channel(channel_id: str, source_url: str) -> dict:
    url = f"{_base_url()}/channels/{channel_id}/start"
    try:
        client = _get_live_client()
        response = await client.post(
            url, headers=_headers(), json={"source_url": source_url}
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=_error_detail(exc, "Could not start channel"),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach live TV service",
        ) from exc
    data = response.json()
    return data if isinstance(data, dict) else {}


async def stop_channel(channel_id: str) -> dict:
    url = f"{_base_url()}/channels/{channel_id}/stop"
    try:
        client = _get_live_client()
        response = await client.post(url, headers=_headers())
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=_error_detail(exc, "Could not stop channel"),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach live TV service",
        ) from exc
    data = response.json()
    return data if isinstance(data, dict) else {"status": "offline"}


async def get_channel_status(channel_id: str) -> dict:
    url = f"{_base_url()}/channels/{channel_id}/status"
    try:
        client = _get_live_client()
        response = await client.get(url, headers=_headers())
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=_error_detail(exc, "Could not fetch channel status"),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach live TV service",
        ) from exc
    data = response.json()
    return data if isinstance(data, dict) else {}
