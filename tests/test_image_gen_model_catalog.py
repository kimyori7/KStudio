"""image_gen.model_catalog — 카탈로그 정합성 + 정렬 + dispatch 키 검증.

heavy diffusers 의존성은 불필요 — 카탈로그는 순수 데이터.
"""
from __future__ import annotations


def test_catalog_has_five_entries():
    from screen_recorder.image_gen.model_catalog import CATALOG
    assert len(CATALOG) == 5


def test_quality_rank_unique_and_sequential():
    from screen_recorder.image_gen.model_catalog import CATALOG
    ranks = [e.quality_rank for e in CATALOG]
    assert sorted(ranks) == list(range(1, len(CATALOG) + 1))
    assert len(set(ranks)) == len(ranks)


def test_t2i_models_sorted_by_quality():
    from screen_recorder.image_gen.model_catalog import t2i_models
    items = t2i_models()
    ranks = [e.quality_rank for e in items]
    assert ranks == sorted(ranks)
    # FLUX-dev (1) 가 첫번째.
    assert items[0].id == "flux1-dev"


def test_i2i_models_exclude_pixart():
    """PixArt-Sigma 는 i2i 미지원 — i2i 목록엔 없어야 함."""
    from screen_recorder.image_gen.model_catalog import i2i_models
    ids = [e.id for e in i2i_models()]
    assert "pixart-sigma-1024ms" not in ids
    assert "sdxl-1.0" in ids
    assert "sd35-medium" in ids


def test_by_id_returns_entry():
    from screen_recorder.image_gen.model_catalog import by_id
    e = by_id("sdxl-1.0")
    assert e is not None
    assert e.display_name == "SDXL 1.0"
    assert e.backend_kind == "sdxl"
    assert by_id("nonexistent") is None


def test_default_model_picks_highest_quality_implemented():
    """default_model_for_mode 는 is_implemented=True 중 quality_rank 최상."""
    from screen_recorder.image_gen.model_catalog import default_model_for_mode
    # Phase 1 구현: sd35-medium (rank 3), sdxl-1.0 (rank 4), pixart (rank 5).
    # FLUX-dev / SD 3.5 Large 는 is_implemented=False.
    assert default_model_for_mode("t2i").id == "sd35-medium"
    assert default_model_for_mode("i2i").id == "sd35-medium"


def test_phase1_implemented_backends():
    """Phase 1 출시 시 실제 generate 가능한 backend 목록."""
    from screen_recorder.image_gen.model_catalog import CATALOG
    implemented = {e.id for e in CATALOG if e.is_implemented}
    assert implemented == {"sdxl-1.0", "sd35-medium", "pixart-sigma-1024ms"}


def test_unimplemented_models_are_flagged():
    """FLUX / SD 3.5 Large 는 카탈로그엔 보이지만 미구현 표시."""
    from screen_recorder.image_gen.model_catalog import by_id
    assert by_id("flux1-dev").is_implemented is False
    assert by_id("sd35-large").is_implemented is False


def test_estimated_size_bytes_positive():
    from screen_recorder.image_gen.model_catalog import CATALOG, estimated_size_bytes
    for e in CATALOG:
        b = estimated_size_bytes(e)
        assert b > 0
        # 모든 모델은 최소 1GB 이상.
        assert b >= 1024 ** 3


def test_license_labels_non_empty():
    from screen_recorder.image_gen.model_catalog import CATALOG
    for e in CATALOG:
        assert e.license_label, f"{e.id} missing license_label"


def test_backend_kind_known_values():
    from screen_recorder.image_gen.model_catalog import CATALOG
    known = {"pixart", "sdxl", "sd35_medium", "sd35_large", "flux"}
    for e in CATALOG:
        assert e.backend_kind in known, f"{e.id} unknown backend_kind: {e.backend_kind}"


def test_sdxl_has_fp16_allow_patterns():
    """SDXL 은 fp16 variant 만 받게 allow_patterns 박혀있어야 — 사용자 보고 2026-05-27
    (snapshot_download 가 모든 variant 받아 28GB 다운로드)."""
    from screen_recorder.image_gen.model_catalog import by_id
    e = by_id("sdxl-1.0")
    assert e.download_allow_patterns is not None
    assert any("fp16" in p for p in e.download_allow_patterns)


def test_sd35_medium_has_fp16_allow_patterns():
    from screen_recorder.image_gen.model_catalog import by_id
    e = by_id("sd35-medium")
    assert e.download_allow_patterns is not None
    assert any("fp16" in p for p in e.download_allow_patterns)


def test_pixart_uses_ignore_patterns_not_allow():
    """PixArt 는 variant 없음 — allow_patterns 대신 ignore 로 무거운 무관 파일 제외."""
    from screen_recorder.image_gen.model_catalog import by_id
    e = by_id("pixart-sigma-1024ms")
    assert e.download_allow_patterns is None
    assert e.download_ignore_patterns is not None
    assert any(p == "*.bin" for p in e.download_ignore_patterns)
