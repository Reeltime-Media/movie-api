import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test")
os.environ.setdefault("R2_ACCOUNT_ID", "test")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("R2_BUCKET_NAME", "movies")
os.environ.setdefault("R2_PUBLIC_URL", "https://cdn.test")
os.environ.setdefault("PLAYBACK_SEGMENT_MODE", "cdn")

from app.config import clear_settings_cache, get_settings
from app.services import storage


def test_playback_segment_url_uses_public_cdn_by_default():
    clear_settings_cache()
    os.environ["PLAYBACK_SEGMENT_MODE"] = "cdn"
    clear_settings_cache()
    cfg = get_settings()
    url = storage.generate_playback_segment_url("movies/demo/hls/720p_000.ts")
    assert url == f"{cfg.r2_public_url.rstrip('/')}/movies/demo/hls/720p_000.ts"


def test_playback_segment_url_presign_mode(monkeypatch):
    clear_settings_cache()
    os.environ["PLAYBACK_SEGMENT_MODE"] = "presign"
    clear_settings_cache()

    monkeypatch.setattr(
        storage,
        "generate_presigned_download_url",
        lambda key, expires_in=3600: f"https://r2.example/{key}?sig=1&exp={expires_in}",
    )
    url = storage.generate_playback_segment_url("movies/demo/hls/720p_000.ts", 120)
    assert url.startswith("https://r2.example/movies/demo/hls/720p_000.ts?")
    clear_settings_cache()
    os.environ["PLAYBACK_SEGMENT_MODE"] = "cdn"
    clear_settings_cache()
    _ = get_settings()
