"""Key layout for hero slide media uploads."""

import uuid

from app.services import r2_keys


def test_hero_banner_key_uses_image_extension():
    media_id = uuid.uuid4()
    key = r2_keys.hero_banner_key(media_id, "image/png")
    assert key == f"hero/banners/{media_id}.png"


def test_hero_video_key_mp4():
    media_id = uuid.uuid4()
    key = r2_keys.hero_video_key(media_id, "video/mp4")
    assert key == f"hero/videos/{media_id}.mp4"


def test_hero_video_key_webm():
    media_id = uuid.uuid4()
    key = r2_keys.hero_video_key(media_id, "video/webm")
    assert key == f"hero/videos/{media_id}.webm"
