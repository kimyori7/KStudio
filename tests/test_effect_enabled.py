"""Effect.enabled (개별) + Sidecar.effects_enabled (전체) — 효과 ON/OFF.

2026-05-20 사용자 요청: "전체 편집 활성/비활성 + 개별 효과 라인별 활성/비활성".

데이터 모델:
- Effect.enabled (개별 효과 단위) — preview + export 모두 무시할지
- Sidecar.effects_enabled (전체 토글) — 한 번에 모든 효과 무시
- 적용 규칙: effects_enabled AND eff.enabled 면 적용

사이드카 backward compat — 누락된 필드는 default (True) 로 자동.
"""
from __future__ import annotations

import json
import pytest

from screen_recorder.effects.sidecar import Sidecar, _effect_from_dict, _effect_to_dict
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.effects.types.cut import CutEffect


# ============================================================
# Effect.enabled 기본값 + 직렬화
# ============================================================
def test_caption_default_enabled_true():
    c = CaptionEffect(in_ms=0, out_ms=1000, text="hi")
    assert c.enabled is True


def test_cut_default_enabled_true():
    c = CutEffect(in_ms=1000, out_ms=2000)
    assert c.enabled is True


def test_caption_explicit_disabled():
    c = CaptionEffect(in_ms=0, out_ms=1000, text="hi", enabled=False)
    assert c.enabled is False


def test_effect_enabled_roundtrip_dict():
    """직렬화 → 역직렬화 시 enabled 보존."""
    c = CaptionEffect(in_ms=0, out_ms=1000, text="hi", enabled=False)
    d = _effect_to_dict(c)
    assert d["enabled"] is False
    c2 = _effect_from_dict(d)
    assert c2.enabled is False


def test_effect_dict_without_enabled_defaults_true():
    """기존 사이드카 (enabled 필드 없음) → load 시 default True."""
    d = {"type": "caption", "in_ms": 0, "out_ms": 1000, "text": "hi"}
    c = _effect_from_dict(d)
    assert c.enabled is True


# ============================================================
# Sidecar.effects_enabled (전체 토글)
# ============================================================
def test_sidecar_default_effects_enabled_true():
    sc = Sidecar(source_path="x", source_hash="h")
    assert sc.effects_enabled is True


def test_sidecar_explicit_effects_disabled():
    sc = Sidecar(source_path="x", source_hash="h", effects_enabled=False)
    assert sc.effects_enabled is False


def test_sidecar_effects_enabled_roundtrip(tmp_path):
    """to_dict / from_dict 로 보존."""
    sc = Sidecar(source_path="x", source_hash="h", effects_enabled=False)
    d = sc.to_dict()
    assert d["effects_enabled"] is False
    sc2 = Sidecar.from_dict(d)
    assert sc2.effects_enabled is False


def test_sidecar_old_dict_without_effects_enabled_defaults_true():
    """기존 사이드카 (effects_enabled 필드 없음) → load 시 default True."""
    d = {
        "version": 3, "source_path": "x", "source_hash": "h",
        "video_track": [], "trim": {"in_ms": 0, "out_ms": 0}, "effects": [],
    }
    sc = Sidecar.from_dict(d)
    assert sc.effects_enabled is True


# ============================================================
# Sidecar.active_effects() — 모든 preview/export 코드의 단일 진입점
# 전체 토글 + 개별 토글 둘 다 통과한 효과만 반환.
# ============================================================
def test_active_effects_all_enabled():
    sc = Sidecar(source_path="x", source_hash="h", effects=[
        CaptionEffect(in_ms=0, out_ms=1000, text="a"),
        CutEffect(in_ms=2000, out_ms=3000),
    ])
    assert len(sc.active_effects()) == 2


def test_active_effects_global_disabled_returns_empty():
    """전체 토글 OFF → 개별 enabled 값 무관, 빈 리스트."""
    sc = Sidecar(source_path="x", source_hash="h", effects_enabled=False, effects=[
        CaptionEffect(in_ms=0, out_ms=1000, text="a"),
        CutEffect(in_ms=2000, out_ms=3000),
    ])
    assert sc.active_effects() == []


def test_active_effects_individual_disabled_filtered():
    """전체 ON + 개별 OFF — 그 효과만 제외."""
    sc = Sidecar(source_path="x", source_hash="h", effects=[
        CaptionEffect(in_ms=0, out_ms=1000, text="a", enabled=True),
        CaptionEffect(in_ms=2000, out_ms=3000, text="b", enabled=False),
        CutEffect(in_ms=4000, out_ms=5000, enabled=False),
    ])
    active = sc.active_effects()
    assert len(active) == 1
    assert active[0].text == "a"


def test_active_effects_empty_returns_empty():
    sc = Sidecar(source_path="x", source_hash="h")
    assert sc.active_effects() == []


# ============================================================
# EditController.set_effects_enabled / set_row_enabled
# ============================================================
def test_set_effects_enabled_toggles_and_emits(tmp_path):
    from screen_recorder.ui.video.edit_controller import EditController
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 4096)
    ec = EditController(video, tmp_path)
    assert ec.sidecar().effects_enabled is True

    # True → False.
    received = []
    ec.sidecar_replaced.connect(received.append)
    assert ec.set_effects_enabled(False) is True
    assert ec.sidecar().effects_enabled is False
    assert len(received) == 1
    # 같은 값 재호출 — no-op.
    assert ec.set_effects_enabled(False) is False
    assert len(received) == 1


def test_set_row_enabled_changes_only_matching_effects(tmp_path):
    """type + track_idx 매치하는 효과만 변경."""
    from screen_recorder.ui.video.edit_controller import EditController
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 4096)
    ec = EditController(video, tmp_path)
    # 사이드카 직접 주입 — 3개 caption 다른 track_idx.
    ec._sidecar.effects = [
        CaptionEffect(in_ms=0, out_ms=1000, text="a", track_idx=0),
        CaptionEffect(in_ms=2000, out_ms=3000, text="b", track_idx=0),
        CaptionEffect(in_ms=4000, out_ms=5000, text="c", track_idx=1),   # 다른 row
    ]
    assert ec.set_row_enabled("caption", 0, False) is True
    effs = ec.sidecar().effects
    # track_idx=0 의 두 효과 OFF, track_idx=1 의 1개는 그대로.
    assert effs[0].enabled is False
    assert effs[1].enabled is False
    assert effs[2].enabled is True


def test_set_row_enabled_undo_restores(tmp_path):
    """한 번의 토글은 single history entry — undo 1번이면 복원."""
    from screen_recorder.ui.video.edit_controller import EditController
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 4096)
    ec = EditController(video, tmp_path)
    ec._sidecar.effects = [
        CaptionEffect(in_ms=0, out_ms=1000, text="a", track_idx=0),
        CaptionEffect(in_ms=2000, out_ms=3000, text="b", track_idx=0),
    ]
    ec.set_row_enabled("caption", 0, False)
    assert all(e.enabled is False for e in ec.sidecar().effects)
    ec.undo()
    assert all(e.enabled is True for e in ec.sidecar().effects)
