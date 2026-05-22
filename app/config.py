from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Movies API"
    debug: bool = False
    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001"
    )
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours

    # Database — Supabase PostgreSQL
    database_url: str  # postgresql+asyncpg://... (direct host; may be IPv6-only)
    # IPv4 pooler — use for Alembic from your Mac and for Docker (see root .env)
    pooler_database_url: str | None = None
    transcode_database_url: str | None = None

    @property
    def alembic_database_url(self) -> str:
        """Prefer pooler URL so migrations work from host and Docker."""
        return self.pooler_database_url or self.transcode_database_url or self.database_url

    # Cloudflare R2
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket_name: str
    r2_public_url: str  # CDN / public bucket URL prefix

    # Baray Payment Gateway
    baray_api_key: str = ""
    baray_sk: str = ""
    baray_iv: str = ""
    baray_base_url: str = "https://api.baray.io"
    baray_checkout_base_url: str = "https://pay.baray.io"
    # Public URL of this API — must be reachable by Baray to deliver webhooks
    api_public_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
