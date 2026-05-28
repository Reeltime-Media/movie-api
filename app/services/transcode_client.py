"""Server-side proxy to the transcode worker (keeps API key off the browser)."""

import httpx
from fastapi import HTTPException, status

from app.config import get_settings

_CLIENT_TIMEOUT_SECONDS = 15
_transcode_client: httpx.AsyncClient | None = None


def _headers() -> dict[str, str]:
    settings = get_settings()
    headers: dict[str, str] = {"Accept": "application/json"}
    if settings.transcode_api_key:
        headers["X-Api-Key"] = settings.transcode_api_key
    return headers


def _base_url() -> str:
    settings = get_settings()
    if not settings.transcode_service_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcode service is not configured",
        )
    return settings.transcode_service_url.rstrip("/")


def _get_transcode_client() -> httpx.AsyncClient:
    global _transcode_client
    if _transcode_client is None:
        _transcode_client = httpx.AsyncClient(timeout=_CLIENT_TIMEOUT_SECONDS)
    return _transcode_client


async def close_http_client() -> None:
    global _transcode_client
    if _transcode_client is not None:
        await _transcode_client.aclose()
        _transcode_client = None


async def fetch_jobs_progress() -> dict[str, int]:
    url = f"{_base_url()}/jobs/progress"
    try:
        client = _get_transcode_client()
        response = await client.get(url, headers=_headers())
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach transcode service",
        ) from exc
    data = response.json()
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid transcode progress response",
        )
    return {str(k): int(v) for k, v in data.items() if isinstance(v, (int, float))}


async def cancel_job(job_id: str) -> dict:
    url = f"{_base_url()}/jobs/{job_id}/cancel"
    try:
        client = _get_transcode_client()
        response = await client.post(url, headers=_headers())
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = "Could not cancel transcode job"
        try:
            body = exc.response.json()
            if isinstance(body, dict) and isinstance(body.get("detail"), str):
                detail = body["detail"]
        except ValueError:
            pass
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach transcode service",
        ) from exc
    data = response.json()
    return data if isinstance(data, dict) else {"job_id": job_id, "cancelled": True}
