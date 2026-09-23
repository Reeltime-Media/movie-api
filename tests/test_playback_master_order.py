import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test")
os.environ.setdefault("R2_ACCOUNT_ID", "test")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("R2_BUCKET_NAME", "movies")
os.environ.setdefault("R2_PUBLIC_URL", "https://cdn.test")

from app.services.playback import order_master_playlist_for_startup


def test_orders_variants_lowest_bandwidth_first():
    body = order_master_playlist_for_startup(
        """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=12000000,RESOLUTION=3840x2160
v/4k.m3u8?t=tok
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080
v/1080p.m3u8?t=tok
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
v/360p.m3u8?t=tok
"""
    )
    urls = [line for line in body.splitlines() if not line.startswith("#") and line]
    assert urls == [
        "v/360p.m3u8?t=tok",
        "v/1080p.m3u8?t=tok",
        "v/4k.m3u8?t=tok",
    ]


def test_keeps_preamble_ahead_of_stream_inf():
    body = order_master_playlist_for_startup(
        """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1280x720
v/720p.m3u8?t=tok
#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=854x480
v/480p.m3u8?t=tok
"""
    )
    lines = body.splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[1] == "#EXT-X-VERSION:3"
    assert "BANDWIDTH=1500000" in lines[2]
    assert lines[3] == "v/480p.m3u8?t=tok"
