import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test")
os.environ.setdefault("R2_ACCOUNT_ID", "test")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("R2_BUCKET_NAME", "test")
os.environ.setdefault("R2_PUBLIC_URL", "https://cdn.test")

from io import BytesIO

from PIL import Image

from app.services.image_process import optimize_image_bytes


def _solid_jpeg_bytes(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color=(120, 40, 200))
    out = BytesIO()
    img.save(out, format="JPEG", quality=95)
    return out.getvalue()


def test_optimize_poster_downsizes_and_webps():
    original = _solid_jpeg_bytes(2400, 3600)
    optimized = optimize_image_bytes(original, kind="poster")
    assert len(optimized) < len(original)
    with Image.open(BytesIO(optimized)) as img:
        assert img.format == "WEBP"
        assert img.size[0] <= 800


def test_optimize_banner_downsizes_and_webps():
    original = _solid_jpeg_bytes(3840, 2160)
    optimized = optimize_image_bytes(original, kind="banner")
    assert len(optimized) < len(original)
    with Image.open(BytesIO(optimized)) as img:
        assert img.format == "WEBP"
        assert img.size[0] <= 1920
