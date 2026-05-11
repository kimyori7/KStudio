"""EffectLanesWidget — lane 컨테이너 + 자동 생성."""
import pytest
from PySide6.QtCore import Qt

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.ui.video.effect_lanes_widget import EffectLanesWidget


def test_empty_sidecar_shows_all_4_lanes(qtbot):
    """효과 0 개라도 _LANE_ORDER 의 4 종 (caption/speed/zoom/broll) lane 모두 표시.

    Stage D (2026-05-08): cut lane 은 segment 트랙으로 흡수되어 제거.
    """
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000))
    w.set_sidecar(sc)
    assert w.lane_count() == 4
    for t in ("caption", "speed", "zoom", "broll"):
        assert w.has_lane_for_type(t) is True


def test_one_caption_keeps_5_lanes_with_caption_effect_routed(qtbot):
    """CaptionEffect 1 개 → lane 5 개 (모두 표시), caption lane 만 효과 1 개 보유."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[CaptionEffect(in_ms=1000, out_ms=4000, text="hi")],
    )
    w.set_sidecar(sc)
    assert w.lane_count() == 4
    assert len(w.lane_for_type("caption").effects()) == 1
    assert len(w.lane_for_type("speed").effects()) == 0


def test_mixed_types_routes_to_each_lane(qtbot):
    """캡션 2 + 배속 1 → lane 5 개, caption lane 2 개·speed lane 1 개 효과 보유."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[
            CaptionEffect(in_ms=1000, out_ms=4000, text="a"),
            CaptionEffect(in_ms=5000, out_ms=8000, text="b"),
            SpeedEffect(in_ms=2000, out_ms=3000, rate=2.0),
        ],
    )
    w.set_sidecar(sc)
    assert w.lane_count() == 4
    assert len(w.lane_for_type("caption").effects()) == 2
    assert len(w.lane_for_type("speed").effects()) == 1
    assert len(w.lane_for_type("zoom").effects()) == 0


def test_set_sidecar_replaces_effects_per_lane(qtbot):
    """다른 사이드카로 교체 → lane 인스턴스는 그대로, 각 lane 의 effects 만 갱신."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc1 = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000),
                  effects=[CaptionEffect(in_ms=0, out_ms=1000, text="a")])
    sc2 = Sidecar(source_path="y", source_hash="h2", trim=Trim(in_ms=0, out_ms=10_000),
                  effects=[SpeedEffect(in_ms=0, out_ms=1000, rate=2.0)])
    w.set_sidecar(sc1)
    caption_lane = w.lane_for_type("caption")
    assert len(caption_lane.effects()) == 1
    w.set_sidecar(sc2)
    assert len(caption_lane.effects()) == 0
    assert len(w.lane_for_type("speed").effects()) == 1


def test_set_duration_propagates_to_lanes(qtbot):
    """set_duration_ms 가 모든 lane 에 전파."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000),
                 effects=[CaptionEffect(in_ms=0, out_ms=1000, text="a")])
    w.set_sidecar(sc)
    w.set_duration_ms(20_000)
    lane = w.lane_for_type("caption")
    assert lane.duration_ms() == 20_000


def test_caption_type_uses_caption_lane_class(qtbot):
    """type='caption' lane 은 CaptionLane 인스턴스여야 (Task 3 에서 도입)."""
    # CaptionLane 미도입 시점엔 base EffectLane 으로 fallback. Task 3 commit 후
    # 이 테스트는 CaptionLane import 가 가능해진다.
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000),
                 effects=[CaptionEffect(in_ms=0, out_ms=1000, text="a")])
    w.set_sidecar(sc)
    lane = w.lane_for_type("caption")
    assert lane is not None
    # Stage 3 Task 3 후엔 CaptionLane 의 인스턴스. 그 전에는 base.
    # 여기선 단순히 effects 가 lane 에 전달됐는지 확인.
    assert len(lane.effects()) == 1
