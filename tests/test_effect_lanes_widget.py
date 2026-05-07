"""EffectLanesWidget — lane 컨테이너 + 자동 생성."""
import pytest
from PySide6.QtCore import Qt

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.ui.video.effect_lanes_widget import EffectLanesWidget


def test_empty_sidecar_no_lanes(qtbot):
    """효과 0 개 → lane 0 개."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000))
    w.set_sidecar(sc)
    assert w.lane_count() == 0


def test_one_caption_creates_caption_lane(qtbot):
    """CaptionEffect 1 개 → 캡션 lane 1 개."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[CaptionEffect(in_ms=1000, out_ms=4000, text="hi")],
    )
    w.set_sidecar(sc)
    assert w.lane_count() == 1
    assert w.has_lane_for_type("caption") is True
    assert w.has_lane_for_type("speed") is False


def test_mixed_types_creates_multiple_lanes(qtbot):
    """캡션 2 + 배속 1 → lane 2 개 (type 별 1개씩)."""
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
    assert w.lane_count() == 2
    assert w.has_lane_for_type("caption") is True
    assert w.has_lane_for_type("speed") is True


def test_set_sidecar_replaces_lanes(qtbot):
    """다른 사이드카로 교체 → 기존 lane 제거 후 새로 생성."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc1 = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000),
                  effects=[CaptionEffect(in_ms=0, out_ms=1000, text="a")])
    sc2 = Sidecar(source_path="y", source_hash="h2", trim=Trim(in_ms=0, out_ms=10_000),
                  effects=[SpeedEffect(in_ms=0, out_ms=1000, rate=2.0)])
    w.set_sidecar(sc1)
    assert w.has_lane_for_type("caption") is True
    w.set_sidecar(sc2)
    assert w.has_lane_for_type("caption") is False
    assert w.has_lane_for_type("speed") is True


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


def test_request_add_at_bubbles_with_type(qtbot):
    """lane 이 발생시킨 request_add_at 이 컨테이너에서 (type, ms) 로 bubble."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000),
                 effects=[CaptionEffect(in_ms=0, out_ms=1000, text="a")])
    w.set_sidecar(sc)
    lane = w.lane_for_type("caption")
    # 직접 lane 의 시그널 발화 (마우스 시뮬레이션 대신)
    with qtbot.waitSignal(w.request_add, timeout=1000) as blocker:
        lane.request_add_at.emit(5000)
    assert blocker.args == ["caption", 5000]
