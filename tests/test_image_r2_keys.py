"""Poster/banner keys must change on every upload so the stored key (and URL) change."""

import re
import uuid

from app.services import r2_keys
from app.services.image_process import poster_thumb_key_for, webp_key_for


def test_movie_poster_key_is_unique_per_upload():
    first = r2_keys.movie_poster_key("tune-in-for-love-2019", "image/jpeg")
    second = r2_keys.movie_poster_key("tune-in-for-love-2019", "image/jpeg")
    assert first != second
    assert re.fullmatch(r"movies/tune-in-for-love-2019/poster-[0-9a-f]{12}\.jpg", first)


def test_every_image_key_generator_is_unique_and_passes_its_validator():
    banner_id = uuid.uuid4()
    cases = [
        (
            lambda: r2_keys.movie_poster_key("m", "image/png"),
            lambda k: r2_keys.is_movie_asset_key("m", k),
        ),
        (
            lambda: r2_keys.movie_banner_key("m", "image/png"),
            lambda k: r2_keys.is_movie_asset_key("m", k),
        ),
        (
            lambda: r2_keys.series_poster_key("s", "image/webp"),
            lambda k: r2_keys.is_series_asset_key("s", k),
        ),
        (
            lambda: r2_keys.series_banner_key("s", "image/webp"),
            lambda k: r2_keys.is_series_asset_key("s", k),
        ),
        (
            lambda: r2_keys.episode_poster_key("s", "s-s01e01", "image/jpeg"),
            lambda k: r2_keys.is_episode_asset_key("s", "s-s01e01", k),
        ),
        (
            lambda: r2_keys.promotion_banner_image_key(banner_id, "image/jpeg"),
            lambda k: r2_keys.is_promotion_banner_image_key(banner_id, k),
        ),
    ]
    for make, is_valid in cases:
        a, b = make(), make()
        assert a != b
        assert is_valid(a)


def test_optimized_and_thumb_keys_derive_from_tokened_name():
    key = "movies/m/poster-0123456789ab.jpg"
    optimized = webp_key_for(key)
    assert optimized == "movies/m/poster-0123456789ab.webp"
    assert poster_thumb_key_for(optimized) == "movies/m/poster-0123456789ab-w400.webp"
