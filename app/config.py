from functools import lru_cache
from typing import Self
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# movie-client (:3000) and movie-admin (:3001)
LOCAL_DEV_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
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
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Movies API"
    debug: bool = False
    cors_origins: str = Field(default_factory=default_cors_origins)
    # Allow all Vercel production + preview URLs (e.g. *-team.vercel.app)
    cors_origin_regex: str = r"https://.*\.vercel\.app"
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours
    # Public frontend URL(s) for payment success redirects (comma-separated; falls back to CORS_ORIGINS)
    app_public_url: str = ""

    # Google Sign-In (OAuth client ID from Google Cloud Console)
    google_client_id: str = ""  # env: GOOGLE_CLIENT_ID

    # Database — Supabase PostgreSQL
    database_url: str  # postgresql+asyncpg://... (direct host; may be IPv6-only)
    # IPv4 pooler — use for Alembic from your Mac and for Docker (see root .env)
    pooler_database_url: str | None = None
    # Path to the Supabase CA bundle (Project Settings → Database → SSL certificate).
    # When set, database TLS is verified; when empty, TLS is used but unverified.
    database_ssl_root_cert: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed CORS_ORIGINS plus local dev frontends (3000 client, 3001 admin)."""
        from_env = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        seen: set[str] = set()
        merged: list[str] = []
        for origin in (*LOCAL_DEV_CORS_ORIGINS, *from_env):
            if origin not in seen:
                seen.add(origin)
                merged.append(origin)
        return merged

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

    # How long an issued playback token (and its presigned segment URLs) stays
    # valid. Must exceed the longest title's runtime so a stream doesn't expire
    # mid-watch. Default 6h.
    playback_token_expiry_seconds: int = 21600

    # Baray Payment Gateway
    baray_api_key: str = ""
    baray_sk: str = ""
    baray_iv: str = ""
    baray_base_url: str = "https://api.baray.io"
    baray_checkout_base_url: str = "https://pay.baray.io"
    baray_webhook_secret: str = ""
    # Public URL of this API — must be reachable by Baray to deliver webhooks
    api_public_url: str = ""

    # Bakong KHQR (National Bank of Cambodia) — inline QR checkout, no redirect.
    # Register a developer token at api-bakong.nbc.gov.kh (requires Cambodia-hosted
    # servers) or use an "rbk_"-prefixed relay token from bakongrelay.com otherwise.
    bakong_developer_token: str = ""
    bakong_account_id: str = ""  # format: username@bank
    bakong_merchant_name: str = ""
    bakong_merchant_city: str = "Phnom Penh"
    # Optional override (e.g. https://api.bakongrelay.com/v1). Empty = auto from token.
    bakong_api_base_url: str = ""

    # Transcode worker (admin proxy only — never expose key to browsers)
    transcode_service_url: str = ""
    transcode_api_key: str = ""

    # Resend (transactional email — password reset, etc.)
    resend_api_key: str = ""
    resend_from_email: str = "Reeltime <onboarding@resend.dev>"
    password_reset_token_expire_minutes: int = 30

    # Concurrent device sessions allowed per account before login is rejected
    max_active_sessions_per_user: int = 3

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

        if self.bakong_developer_token.strip() and (
            not self.bakong_account_id.strip() or not self.bakong_merchant_name.strip()
        ):
            raise ValueError(
                "BAKONG_ACCOUNT_ID and BAKONG_MERCHANT_NAME are required when "
                "BAKONG_DEVELOPER_TOKEN is set (DEBUG is false)"
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    """Reset cached settings (use in tests or after env changes)."""
    get_settings.cache_clear()
