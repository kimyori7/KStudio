"""image_gen.model_meta 가벼운 검증."""
from __future__ import annotations


def test_default_meta_is_pixart_sigma():
    from screen_recorder.image_gen.model_meta import MODEL_META

    assert MODEL_META.id == "pixart-sigma-1024ms"
    assert MODEL_META.repo_id == "PixArt-alpha/PixArt-Sigma-XL-2-1024-MS"
    assert MODEL_META.default_steps == 20
    assert MODEL_META.default_resolution == 1024
    assert MODEL_META.supports_korean is True


def test_estimated_size_bytes_returns_int():
    from screen_recorder.image_gen.model_meta import (
        MODEL_META, estimated_size_bytes,
    )

    n = estimated_size_bytes()
    assert isinstance(n, int)
    # 6.3GB 면 약 6.7e9 bytes — 부호/단위 sanity 만 확인.
    assert 5 * 1024**3 < n < 8 * 1024**3
    assert n == estimated_size_bytes(MODEL_META)
