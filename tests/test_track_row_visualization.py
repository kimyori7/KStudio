"""Phase 28 — track_idx 별 row 시각화 + 빈 lane 추가 회귀."""
from __future__ import annotations

import pytest

from screen_recorder.effects import Sidecar
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.effects.types.broll import BrollEffect, PipConfig
from screen_recorder.effects.types.arrow import ArrowEffect
from screen_recorder.ui.video.caption_lane import CaptionLane
from screen_recorder.ui.video.arrow_lane import ArrowLane
from screen_recorder.ui.video.broll_lane import BrollLane
from screen_recorder.ui.video.effect_lanes_widget import EffectLanesWidget


def _cap(in_ms, out_ms, text="hi", track_idx=0):
    return CaptionEffect(in_ms=in_ms, out_ms=out_ms, text=text, track_idx=track_idx)


def test_caption_lane_row_count_matches_max_track(qtbot):
    """track_idx 0/1/2 효과 → row 3개 (height = 3 × 20px)."""
    lane = CaptionLane("caption", "캡션", "#3b82f6")
    qtbot.addWidget(lane)
    lane.set_duration_ms(10_000)
    lane.set_effects([
        _cap(0, 1000, track_idx=0),
        _cap(0, 1000, track_idx=1),
        _cap(0, 1000, track_idx=2),
    ])
    assert lane.row_count() == 3
    assert lane.height() == 3 * lane.TRACK_ROW_HEIGHT


def test_caption_lane_extra_empty_adds_row(qtbot):
    """track_idx 0 효과 1개 + extra_empty=2 → row 3개 (1 used + 2 empty)."""
    lane = CaptionLane("caption", "캡션", "#3b82f6")
    qtbot.addWidget(lane)
    lane.set_duration_ms(10_000)
    lane.set_effects([_cap(0, 1000, track_idx=0)])
    lane.set_extra_empty_rows(2)
    assert lane.row_count() == 3


def test_arrow_lane_row_count_for_multiple_tracks(qtbot):
    lane = ArrowLane("arrow", "화살표", "#f43f5e")
    qtbot.addWidget(lane)
    lane.set_duration_ms(10_000)
    lane.set_effects([
        ArrowEffect(in_ms=0, out_ms=1000, track_idx=0),
        ArrowEffect(in_ms=2000, out_ms=3000, track_idx=1),
    ])
    assert lane.row_count() == 2


def test_broll_lane_row_count_for_multiple_tracks(qtbot):
    lane = BrollLane("broll", "곁들임", "#f59e0b")
    qtbot.addWidget(lane)
    lane.set_duration_ms(10_000)
    lane.set_effects([
        BrollEffect(in_ms=0, out_ms=1000, src="a.mp4", pip=PipConfig(), track_idx=0),
        BrollEffect(in_ms=0, out_ms=1000, src="b.mp4", pip=PipConfig(), track_idx=1),
    ])
    assert lane.row_count() == 2


def test_effect_lanes_widget_add_empty_lane_creates_lane(qtbot):
    """add_empty_lane('caption') → lane 인스턴스 생성 + row 1개 표시."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    w.set_duration_ms(10_000)
    w.set_sidecar(Sidecar())
    assert "caption" not in w._lanes
    w.add_empty_lane("caption")
    assert "caption" in w._lanes
    assert w._extra_empty_lanes["caption"] == 1
    assert w._lanes["caption"].row_count() == 1


def test_effect_lanes_widget_add_empty_persists_across_set_sidecar(qtbot):
    """set_sidecar 재호출 시 빈 lane 정보 보존."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    w.set_duration_ms(10_000)
    w.set_sidecar(Sidecar())
    w.add_empty_lane("arrow")
    # 빈 lane 두 번째 추가.
    w.add_empty_lane("arrow")
    assert w._extra_empty_lanes["arrow"] == 2
    w.set_sidecar(Sidecar())   # 효과 0개 사이드카로 재로드
    assert "arrow" in w._lanes
    assert w._lanes["arrow"].row_count() == 2


def test_lane_right_click_add_consumes_empty_row(qtbot):
    """빈 lane 우클릭으로 효과 추가 시 _extra_empty_lanes 가 감소 — 라인 추가 안 됨.

    시나리오: + 버튼으로 빈 캡션 lane 1줄 → 그 lane 우클릭 → '+ 캡션 추가' →
    extra_empty_lanes=0 (효과가 그 자리를 채움), set_sidecar 재호출 시 row 1줄로 유지.
    """
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    w.set_duration_ms(10_000)
    w.set_sidecar(Sidecar())
    w.add_empty_lane("caption")
    assert w._extra_empty_lanes["caption"] == 1
    # lane 의 request_add_at.emit (우클릭 메뉴 '효과 추가' 클릭 시뮬레이션).
    received: list = []
    w.request_add.connect(lambda t, ms: received.append((t, ms)))
    w._lanes["caption"].request_add_at.emit(3_000)
    # extra_empty 가 감소, request_add 발화.
    assert "caption" not in w._extra_empty_lanes or w._extra_empty_lanes["caption"] == 0
    assert received == [("caption", 3_000)]


def test_lane_right_click_add_without_empty_just_emits(qtbot):
    """기존 효과 있는 lane 의 빈 영역 우클릭은 단순 효과 추가 (extra 감소 X)."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    w.set_duration_ms(10_000)
    sc = Sidecar(effects=[_cap(0, 1000, track_idx=0)])
    w.set_sidecar(sc)
    assert "caption" in w._lanes
    received: list = []
    w.request_add.connect(lambda t, ms: received.append((t, ms)))
    w._lanes["caption"].request_add_at.emit(5_000)
    # extra 없음, 그냥 emit.
    assert w._extra_empty_lanes.get("caption", 0) == 0
    assert received == [("caption", 5_000)]


def test_remove_lane_decrements_extra_empty(qtbot):
    """lane 우클릭 '이 라인 지우기' → _extra_empty_lanes 줄어듦. effects 0 이면 lane 자체 제거."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    w.set_duration_ms(10_000)
    w.set_sidecar(Sidecar())
    w.add_empty_lane("caption")
    w.add_empty_lane("caption")
    assert w._extra_empty_lanes["caption"] == 2
    # 한 줄 지우기 — extra=1 로.
    w._on_remove_lane_requested("caption")
    assert w._extra_empty_lanes["caption"] == 1
    assert "caption" in w._lanes
    # 또 한 줄 지우기 — extra=0, effects 0 → lane 자체 제거.
    w._on_remove_lane_requested("caption")
    assert "caption" not in w._lanes


def test_remove_lane_with_effects_noop(qtbot):
    """효과가 있는 lane 은 '이 라인 지우기' 가 no-op (효과 보존)."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    w.set_duration_ms(10_000)
    sc = Sidecar(effects=[_cap(0, 1000, track_idx=0)])
    w.set_sidecar(sc)
    assert "caption" in w._lanes
    w._on_remove_lane_requested("caption")
    # 효과 그대로 보존, lane 도 그대로.
    assert "caption" in w._lanes
    assert len(w._lanes["caption"].effects()) == 1


def test_caption_hit_test_isolates_by_track_row(qtbot):
    """다른 track_idx 의 같은 시간대 효과 — y 좌표로 hit 분리."""
    lane = CaptionLane("caption", "캡션", "#3b82f6")
    qtbot.addWidget(lane)
    lane.resize(400, 100)
    lane.set_duration_ms(10_000)
    e0 = _cap(2_000, 5_000, text="row0", track_idx=0)
    e1 = _cap(2_000, 5_000, text="row1", track_idx=1)
    lane.set_effects([e0, e1])
    # x = 같은 시간대. y = row0 / row1.
    body_w = 400 - 56
    x = 56 + int(3_000 / 10_000 * body_w)   # 3s.
    y0 = lane._row_y_top(0) + 5
    y1 = lane._row_y_top(1) + 5
    hit0, _ = lane._hit_test(x, y0)
    hit1, _ = lane._hit_test(x, y1)
    assert hit0 is not None and hit0.id == e0.id
    assert hit1 is not None and hit1.id == e1.id
