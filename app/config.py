from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Movies API"
    debug: bool = False
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours

    # Database — Supabase PostgreSQL
    database_url: str  # postgresql+asyncpg://...

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
