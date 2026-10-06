"""Unit tests for app.config."""

import pytest
from pydantic import ValidationError

from app.config import LOCAL_DEV_CORS_ORIGINS, Settings, clear_settings_cache, default_cors_origins

_REQUIRED_FIELDS = {
    "secret_key": "a" * 32,
    "database_url": "postgresql+asyncpg://user:pass@localhost/db",
    "r2_account_id": "account",
    "r2_access_key_id": "access-key",
    "r2_secret_access_key": "secret-key",
    "r2_bucket_name": "movies",
    "r2_public_url": "https://cdn.example.com",
    "redis_url": "redis://localhost:6379/0",
}


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**_REQUIRED_FIELDS, **overrides})


class TestCorsDefaults:
    def test_default_cors_origins_matches_local_dev_tuple(self):
        assert default_cors_origins() == ",".join(LOCAL_DEV_CORS_ORIGINS)

    def test_cors_origin_list_merges_and_deduplicates(self):
        settings = make_settings(
            debug=True,
            secret_key="change-me",
            cors_origins="https://app.example.com,http://localhost:3000",
        )
        origins = settings.cors_origin_list
        assert origins[0] == "http://localhost:3000"
        assert "https://app.example.com" in origins
        assert origins.count("http://localhost:3000") == 1

    def test_production_cors_excludes_localhost_defaults(self):
        settings = make_settings(
            cors_origins="https://preview.example.com",
        )
        origins = settings.cors_origin_list
        assert "http://localhost:3000" not in origins
        assert "https://reeltime.fun" in origins
        assert "https://preview.example.com" in origins

    def test_production_rejects_missing_database_ssl_cert(self):
        with pytest.raises(ValidationError, match="DATABASE_SSL_ROOT_CERT"):
            make_settings(
                database_url="postgresql+asyncpg://user:pass@db.supabase.co/db",
            )

    def test_production_allows_insecure_tls_escape(self):
        settings = make_settings(
            database_url="postgresql+asyncpg://user:pass@db.supabase.co/db",
            database_ssl_allow_insecure=True,
        )
        assert settings.database_ssl_allow_insecure is True

    def test_production_rejects_wildcard_vercel_cors_regex(self):
        with pytest.raises(ValidationError, match="CORS_ORIGIN_REGEX"):
            make_settings(cors_origin_regex=r"https://.*\.vercel\.app")

    def test_production_warns_when_redis_url_missing(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            settings = make_settings(redis_url="")
        assert settings.redis_url == ""
        assert any("REDIS_URL is unset" in r.message for r in caplog.records)

    def test_debug_allows_missing_redis_url(self):
        settings = make_settings(debug=True, secret_key="change-me", redis_url="")
        assert settings.redis_url == ""

    def test_access_token_default_is_one_hour(self):
        assert make_settings(debug=True).access_token_expire_minutes == 60


class TestProductionValidation:
    def test_short_secret_key_rejected_when_not_debug(self):
        with pytest.raises(ValidationError, match="SECRET_KEY must be at least 32"):
            make_settings(secret_key="too-short")

    def test_placeholder_secret_key_rejected_when_not_debug(self):
        with pytest.raises(ValidationError, match="placeholder"):
            make_settings(secret_key="change-me-to-a-long-random-string-in-production")

    def test_debug_skips_secret_key_validation(self):
        settings = make_settings(debug=True, secret_key="change-me")
        assert settings.secret_key == "change-me"

    def test_baray_requires_webhook_secret_in_production(self):
        with pytest.raises(ValidationError, match="BARAY_WEBHOOK_SECRET"):
            make_settings(
                baray_api_key="key",
                baray_sk="sk",
                baray_iv="iv",
                api_public_url="https://api.example.com",
            )

    def test_baray_requires_api_public_url_in_production(self):
        with pytest.raises(ValidationError, match="API_PUBLIC_URL"):
            make_settings(
                baray_api_key="key",
                baray_sk="sk",
                baray_iv="iv",
                baray_webhook_secret="whsec",
            )

    def test_baray_accepts_full_config_in_production(self):
        settings = make_settings(
            baray_api_key="key",
            baray_sk="sk",
            baray_iv="iv",
            baray_webhook_secret="whsec",
            api_public_url="https://api.example.com",
        )
        assert settings.baray_api_key == "key"

    def test_transcode_requires_api_key_when_service_url_set(self):
        with pytest.raises(ValidationError, match="TRANSCODE_API_KEY"):
            make_settings(
                transcode_service_url="http://localhost:8001",
                transcode_api_key="",
            )

    def test_transcode_allows_partial_config_in_debug(self):
        settings = make_settings(
            debug=True,
            secret_key="change-me",
            transcode_service_url="http://localhost:8001",
            transcode_api_key="",
        )
        assert settings.transcode_api_key == ""

    def test_live_service_requires_api_key_when_service_url_set(self):
        with pytest.raises(ValidationError, match="LIVE_SERVICE_API_KEY"):
            make_settings(live_service_url="http://localhost:8002")

    def test_live_service_allows_partial_config_in_debug(self):
        settings = make_settings(
            debug=True,
            secret_key="change-me",
            live_service_url="http://localhost:8002",
        )
        assert settings.live_service_api_key == ""


class TestSettingsCache:
    def test_clear_settings_cache_is_safe_to_call(self):
        clear_settings_cache()
        clear_settings_cache()
