from functools import lru_cache
from os import R_OK, access
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# movie-client (:3000) and movie-admin (:3001); Next.js falls back to :3002
# when 3000/3001 are already taken, so allow it too.
LOCAL_DEV_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3002",
)

# reeltime.fun is the production movie-client frontend — the browser origin
# that calls this API (api.reeltime.fun) cross-subdomain. Always allowed
# regardless of what CORS_ORIGINS is set to in the hosting environment.
PRODUCTION_CORS_ORIGINS: tuple[str, ...] = (
    "https://reeltime.fun",
    "https://www.reeltime.fun",
)

_SECRET_KEY_PLACEHOLDERS = frozenset(
    {
        "change-me",
        "change-me-to-a-long-random-string-in-production",
    }
)


def default_cors_origins() -> str:
    return ",".join(LOCAL_DEV_CORS_ORIGINS)


class Settings(BaseSettings):
    # Only read .env when the process can open it (bind-mounted 0600 files break
    # non-root containers). Compose env_file / process env still apply either way.
    model_config = SettingsConfigDict(
        env_file=".env" if access(Path(".env"), R_OK) else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "Movies API"
    debug: bool = False
    cors_origins: str = Field(default_factory=default_cors_origins)
    # Empty by default. Set CORS_ORIGIN_REGEX only for controlled preview hosts
    # (never use a catch-all like https://.*.vercel.app in production).
    cors_origin_regex: str = ""
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60  # 1 hour; logout still revokes via session
    # Public frontend URL(s) for payment success redirects (comma-separated; falls back to CORS_ORIGINS)
    app_public_url: str = ""

    # Google Sign-In (OAuth client ID from Google Cloud Console)
    google_client_id: str = ""  # env: GOOGLE_CLIENT_ID

    # Database — Supabase PostgreSQL
    database_url: str  # postgresql+asyncpg://... (direct host; may be IPv6-only)
    # IPv4 pooler — use for Alembic from your Mac and for Docker (see root .env)
    pooler_database_url: str | None = None
    # Path to the Supabase CA bundle (Project Settings → Database → SSL certificate).
    # Required in production for remote databases unless DATABASE_SSL_ALLOW_INSECURE=true.
    database_ssl_root_cert: str = ""
    # Emergency only — allows unverified TLS when the CA bundle is missing.
    database_ssl_allow_insecure: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS allow-list.

        Production: reeltime.fun + CORS_ORIGINS only (no localhost, no wildcard).
        Debug: also merges local Next.js ports for convenience.
        """
        from_env = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        seen: set[str] = set()
        merged: list[str] = []
        base = (
            (*LOCAL_DEV_CORS_ORIGINS, *PRODUCTION_CORS_ORIGINS, *from_env)
            if self.debug
            else (*PRODUCTION_CORS_ORIGINS, *from_env)
        )
        for origin in base:
            if origin not in seen:
                seen.add(origin)
                merged.append(origin)
        return merged

    @property
    def requires_verified_database_tls(self) -> bool:
        """True when this process must verify the database certificate."""
        if self.debug or self.database_ssl_allow_insecure:
            return False
        host = (
            urlparse(
                self.effective_database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
            ).hostname
            or ""
        )
        return host.lower() not in ("", "localhost", "127.0.0.1")

    @property
    def effective_database_url(self) -> str:
        """Prefer IPv4 pooler when set (Docker and macOS often cannot reach db.* direct host)."""
        return self.pooler_database_url or self.database_url

    @property
    def alembic_database_url(self) -> str:
        return self.effective_database_url

    # Cloudflare R2
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket_name: str
    r2_public_url: str  # CDN / public bucket URL prefix

    # How long an issued playback token (and its segment URLs) stays
    # valid. Must exceed the longest title's runtime so a stream doesn't expire
    # mid-watch. Default 6h.
    playback_token_expiry_seconds: int = 21600
    # cdn = rewrite segments to R2_PUBLIC_URL (Cloudflare edge).
    # presign = private S3-API URLs (bypasses CDN; keep as fallback).
    playback_segment_mode: str = "cdn"

    # Optional shared cache across Uvicorn workers (Upstash / Redis).
    redis_url: str = ""

    # Baray Payment Gateway — off by default; set BARAY_ENABLED=true to mount
    # webhook (+ payment-test when DEBUG) routes again.
    baray_enabled: bool = False
    baray_api_key: str = ""
    baray_sk: str = ""
    baray_iv: str = ""
    baray_base_url: str = "https://api.baray.io"
    baray_checkout_base_url: str = "https://pay.baray.io"
    baray_webhook_secret: str = ""
    # Public URL of this API — must be reachable by Baray to deliver webhooks
    api_public_url: str = ""

    # Bakong KHQR — prefer BAKONG_SERVICE_URL (Cambodia payment-bakong gateway).
    # Local BAKONG_* credentials are only needed when the service URL is empty.
    bakong_service_url: str = ""  # e.g. http://payment-bakong:8010 or https://pay.example.kh
    bakong_service_api_key: str = ""  # shared X-API-Key with payment-bakong
    bakong_developer_token: str = ""
    bakong_account_id: str = ""  # format: username@bank
    bakong_merchant_name: str = ""
    bakong_merchant_city: str = "Phnom Penh"
    # Optional override (e.g. https://api.bakongrelay.com/v1). Empty = auto from token.
    bakong_api_base_url: str = ""
    # App-level QR reuse window (bakong-khqr expiration is whole days, min 1).
    bakong_qr_ttl_minutes: int = 10
    # In-process settle sweeper (covers pay-then-close-tab).
    # Keep this SMALL — NBC ~100 checks/token/day. Long-tail unlock is via
    # playback authorize + reopen checkout, not endless unpaid rechecks.
    bakong_sweeper_interval_seconds: int = 120
    bakong_sweeper_window_minutes: int = 30
    bakong_sweeper_batch_size: int = 2
    # Shared secret for POST /payments/bakong/webhook (DISABLED — no bank credit).
    bakong_webhook_secret: str = ""
    # How far back GET /payments/bakong/pending looks (DISABLED — watcher unused).
    bakong_pending_window_minutes: int = 45
    bakong_pending_limit: int = 20
    # When true: active checkout polls call NBC check_transaction_by_md5
    # (only path Bakong gives for auto-detect paid QR). Admin Mark paid
    # remains the fallback when daily quota is exhausted.
    bakong_nbc_settle_enabled: bool = True
    # Background sweeper (closed-tab). Keep false — client polls
    # + Mark paid cover settle without burning abandoned QRs.
    bakong_sweeper_enabled: bool = False
    # When false, API lifespan skips sweeper/health — run `python -m app.workers.bakong`.
    bakong_run_background_in_api: bool = True

    # Transcode worker (admin proxy only — never expose key to browsers)
    transcode_service_url: str = ""
    transcode_api_key: str = ""

    # Live TV restream service — FFmpeg pulls the source .m3u8 and writes HLS
    # directly to an origin server (fronted by a CDN). This API only
    # orchestrates it (admin proxy) and gates playback; never expose the key
    # to browsers.
    live_service_url: str = ""
    live_service_api_key: str = ""
    # How long a channel playback token stays valid before the frontend must
    # re-authorize. Short-lived since live channels are watched continuously
    # and re-authorizing is cheap (unlike VOD's long runtime window).
    tv_playback_token_expiry_seconds: int = 3600

    # Resend (transactional email — password reset, etc.)
    resend_api_key: str = ""
    resend_from_email: str = "Reeltime <onboarding@resend.dev>"
    password_reset_token_expire_minutes: int = 30

    # TV QR pairing code — short-lived on purpose, re-requested by the TV on expiry
    device_pairing_code_expire_minutes: int = 10

    # Telegram ops alerts (payment success, etc.) — leave empty to disable
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Concurrent device sessions allowed per account before login is rejected
    max_active_sessions_per_user: int = 5

    @model_validator(mode="after")
    def validate_non_debug_settings(self) -> Self:
        if self.debug:
            return self

        key = self.secret_key.strip()
        if len(key) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters when DEBUG is false")
        if key.lower() in _SECRET_KEY_PLACEHOLDERS:
            raise ValueError("SECRET_KEY must not use a placeholder value when DEBUG is false")

        if self.baray_api_key.strip():
            # Credentials present — validate completeness even if BARAY_ENABLED
            # is still false (avoids half-configured prod secrets).
            if not self.baray_webhook_secret.strip():
                raise ValueError(
                    "BARAY_WEBHOOK_SECRET is required when BARAY_API_KEY is set (DEBUG is false)"
                )
            if not self.baray_sk.strip() or not self.baray_iv.strip():
                raise ValueError(
                    "BARAY_SK and BARAY_IV are required when BARAY_API_KEY is set (DEBUG is false)"
                )
            api_url = self.api_public_url.strip()
            if not api_url:
                raise ValueError(
                    "API_PUBLIC_URL is required when Baray is configured (DEBUG is false)"
                )
            parsed = urlparse(api_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError(
                    "API_PUBLIC_URL must be an absolute http(s) URL when DEBUG is false"
                )

        if self.transcode_service_url.strip() and not self.transcode_api_key.strip():
            raise ValueError(
                "TRANSCODE_API_KEY is required when TRANSCODE_SERVICE_URL is set (DEBUG is false)"
            )

        if self.live_service_url.strip() and not self.live_service_api_key.strip():
            raise ValueError(
                "LIVE_SERVICE_API_KEY is required when LIVE_SERVICE_URL is set (DEBUG is false)"
            )

        if self.bakong_service_url.strip():
            if not self.bakong_service_api_key.strip():
                raise ValueError(
                    "BAKONG_SERVICE_API_KEY is required when BAKONG_SERVICE_URL is set "
                    "(DEBUG is false)"
                )
        elif self.bakong_developer_token.strip() and (
            not self.bakong_account_id.strip() or not self.bakong_merchant_name.strip()
        ):
            raise ValueError(
                "BAKONG_ACCOUNT_ID and BAKONG_MERCHANT_NAME are required when "
                "BAKONG_DEVELOPER_TOKEN is set without BAKONG_SERVICE_URL (DEBUG is false)"
            )

        if self.requires_verified_database_tls:
            cert = self.database_ssl_root_cert.strip()
            if not cert:
                raise ValueError(
                    "DATABASE_SSL_ROOT_CERT is required when DEBUG is false "
                    "(set DATABASE_SSL_ALLOW_INSECURE=true only as a temporary escape)"
                )
            cert_path = Path(cert)
            if not cert_path.is_file():
                raise ValueError(f"DATABASE_SSL_ROOT_CERT file not found: {cert}")

        if (
            not self.debug
            and self.cors_origin_regex.strip()
            and ".*" in self.cors_origin_regex
            and "vercel" in self.cors_origin_regex.lower()
        ):
            raise ValueError(
                "CORS_ORIGIN_REGEX must not allow all *.vercel.app hosts when DEBUG is false. "
                "List specific preview origins in CORS_ORIGINS instead."
            )

        # Multi-worker SlowAPI needs shared storage; without Redis each Uvicorn
        # process keeps its own counters and effective limits multiply by workers.
        if not self.redis_url.strip():
            import logging

            logging.getLogger(__name__).warning(
                "REDIS_URL is unset while DEBUG is false — SlowAPI rate limits "
                "will not be shared across Uvicorn workers. Set REDIS_URL in "
                "production (Upstash/Redis) before scaling workers."
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    """Reset cached settings (use in tests or after env changes)."""
    get_settings.cache_clear()
