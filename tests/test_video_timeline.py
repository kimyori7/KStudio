"""VideoTimeline 컨테이너 — 세 자식 lane 통합."""
from __future__ import annotations

import pytest

from screen_recorder.effects import Sidecar
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.ui.video.timeline import (
    VideoTimeline, TimelineSliderLane, TrimMarkerLane,
)
from screen_recorder.ui.video.effect_lanes_widget import EffectLanesWidget


@pytest.fixture
def timeline(qtbot):
    t = VideoTimeline()
    qtbot.addWidget(t)
    t.set_duration_ms(10_000)
    t.set_sidecar(Sidecar())
    return t


def test_has_three_children(timeline):
    assert isinstance(timeline.slider_lane, TimelineSliderLane)
    assert isinstance(timeline.trim_marker_lane, TrimMarkerLane)
    assert isinstance(timeline.effect_lanes, EffectLanesWidget)


def test_set_position_propagates(timeline):
    timeline.set_position_ms(3_000)
    assert timeline.slider_lane.position_ms() == 3_000


def test_set_duration_propagates(timeline):
    timeline.set_duration_ms(20_000)
    assert timeline.slider_lane.duration_ms() == 20_000


def test_edit_mode_off_hides_trim_and_effects(timeline, qtbot):
    timeline.show()
    qtbot.waitExposed(timeline)
    timeline.set_edit_mode(False)
    assert timeline.slider_lane.isVisibleTo(timeline)
    assert not timeline.trim_marker_lane.isVisibleTo(timeline)
    assert not timeline.effect_lanes.isVisibleTo(timeline)


def test_edit_mode_on_shows_trim_and_effects(timeline, qtbot):
    timeline.show()
    qtbot.waitExposed(timeline)
    timeline.set_edit_mode(True)
    assert timeline.trim_marker_lane.isVisibleTo(timeline)
    assert timeline.effect_lanes.isVisibleTo(timeline)


def test_slider_lane_seek_bubbles(timeline, qtbot):
    with qtbot.waitSignal(timeline.seek_request, timeout=300) as blocker:
        timeline.slider_lane.seek_request.emit(2_500)
    assert blocker.args == [2_500]


def test_trim_marker_in_change_swaps_and_emits(timeline, qtbot):
    """in 이 out 보다 뒤로 가면 swap. trim_changed (in, out) 발화."""
    timeline.set_trim(in_ms=2_000, out_ms=5_000)
    with qtbot.waitSignal(timeline.trim_changed, timeout=300) as blocker:
        timeline.trim_marker_lane.in_changed.emit(7_000)
    assert blocker.args == [5_000, 7_000]   # swap 됨


def test_set_trim_updates_marker_lane(timeline):
    timeline.set_trim(in_ms=1_000, out_ms=4_000)
    assert timeline.trim_marker_lane.in_ms() == 1_000
    assert timeline.trim_marker_lane.out_ms() == 4_000


def test_set_sidecar_with_caption_propagates_to_effect_lanes(timeline):
    sc = Sidecar(effects=[CaptionEffect(in_ms=0, out_ms=2000, text="hi")])
    timeline.set_sidecar(sc)
    cap_lane = timeline.effect_lanes.lane_for_type("caption")
    assert cap_lane is not None
    assert len(cap_lane.effects()) == 1


def test_trim_in_drag_to_zero_emits_zero_not_lost(timeline, qtbot):
    """in 마커를 0 으로 드래그하면 (0, out_ms) 가 emit — 0 = 시작점 (Sidecar 와 일관)."""
    timeline.set_trim(in_ms=2_000, out_ms=5_000)
    with qtbot.waitSignal(timeline.trim_changed, timeout=300) as blocker:
        timeline.trim_marker_lane.in_changed.emit(0)
    assert blocker.args == [0, 5_000]


def test_trim_in_drag_with_no_out_emits_zero_for_out(timeline, qtbot):
    """out 이 없는 상태에서 in 만 드래그하면 out 자리에 0 (sentinel) emit."""
    timeline.set_trim(in_ms=2_000, out_ms=None)
    with qtbot.waitSignal(timeline.trim_changed, timeout=300) as blocker:
        timeline.trim_marker_lane.in_changed.emit(3_000)
    assert blocker.args == [3_000, 0]
