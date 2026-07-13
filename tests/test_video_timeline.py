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


def test_playhead_overlay_covers_timeline_and_tracks_position(timeline, qtbot):
    """playhead_overlay 가 컨테이너 전체를 덮고 set_position_ms 가 x 위치 갱신.

    "재생 빨간 세로 줄을 밑에 편집 기능의 기준점이 되게 길게 이어지게" 의도.
    overlay 가 슬라이더 lane 뿐 아니라 video_track + effect_lanes 도 통과해야.
    """
    timeline.resize(800, 200)
    timeline.show()
    qtbot.waitExposed(timeline)
    overlay = timeline.playhead_overlay
    # geometry 가 컨테이너 rect 전체.
    assert overlay.width() == timeline.width()
    assert overlay.height() == timeline.height()
    # position 0 → 헤더 끝.
    timeline.set_position_ms(0)
    x0 = overlay.position_x()
    # position 가운데 → 중간 어딘가.
    timeline.set_position_ms(5_000)
    x5 = overlay.position_x()
    # position 끝 → 컨테이너 끝 근처.
    timeline.set_position_ms(10_000)
    x10 = overlay.position_x()
    assert x0 < x5 < x10
    # transparent for mouse — overlay 가 클릭 가로채면 slider/lane 동작 막힘.
    from PySide6.QtCore import Qt
    assert overlay.testAttribute(Qt.WA_TransparentForMouseEvents)


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


def test_edit_mode_on_shows_effects(timeline, qtbot):
    """Stage D 이후 trim_marker_lane 은 video_track_lane 으로 흡수돼 영구 숨김.
    edit 모드 ON 시 effect_lanes 만 visible.
    """
    timeline.show()
    qtbot.waitExposed(timeline)
    timeline.set_edit_mode(True)
    assert timeline.effect_lanes.isVisibleTo(timeline)
    assert not timeline.trim_marker_lane.isVisibleTo(timeline)


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


def test_zoom_factor_default_one(timeline):
    """초기 zoom = 1.0 (fit-to-window)."""
    assert timeline.zoom_factor() == 1.0


def test_set_zoom_factor_expands_inner_width(timeline, qtbot):
    """zoom 2x → 위/아래 inner 둘 다 minimum width 가 viewport × 2.

    (_inner 는 sticky 상단(_top_inner) + 스크롤 하단(_bottom_inner)으로 분리됨 —
    두 영역의 너비가 같아야 시간축이 정렬된다.)
    """
    timeline.resize(800, 200)
    timeline.show()
    qtbot.waitExposed(timeline)
    vp_w = timeline._scroll.viewport().width()
    timeline.set_zoom_factor(2.0)
    assert timeline._bottom_inner.minimumWidth() == vp_w * 2
    assert timeline._top_inner.minimumWidth() == vp_w * 2


def test_set_zoom_factor_clamped(timeline):
    """zoom 범위 [1.0, 20.0] 밖이면 clamp."""
    timeline.set_zoom_factor(0.5)
    assert timeline.zoom_factor() == 1.0
    timeline.set_zoom_factor(100.0)
    assert timeline.zoom_factor() == 20.0


def test_ctrl_wheel_zooms(timeline, qtbot):
    """Ctrl+휠 위 = 확대, 아래 = 축소."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    timeline.resize(800, 200)
    timeline.show()
    qtbot.waitExposed(timeline)
    # 줌 인 — angleDelta=+120 (한 칸).
    ev_in = QWheelEvent(
        QPointF(100, 50), QPointF(100, 50),
        QPoint(0, 0), QPoint(0, 120),
        Qt.NoButton, Qt.ControlModifier,
        Qt.NoScrollPhase, False,
    )
    timeline.wheelEvent(ev_in)
    assert timeline.zoom_factor() > 1.0
    # 줌 아웃 — angleDelta=-120.
    ev_out = QWheelEvent(
        QPointF(100, 50), QPointF(100, 50),
        QPoint(0, 0), QPoint(0, -120),
        Qt.NoButton, Qt.ControlModifier,
        Qt.NoScrollPhase, False,
    )
    timeline.wheelEvent(ev_out)
    assert timeline.zoom_factor() == 1.0


def test_wheel_without_ctrl_ignored(timeline, qtbot):
    """Ctrl 없는 휠은 zoom 변경 안 함 (부모로 전달)."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    timeline.resize(800, 200)
    timeline.show()
    qtbot.waitExposed(timeline)
    ev = QWheelEvent(
        QPointF(100, 50), QPointF(100, 50),
        QPoint(0, 0), QPoint(0, 120),
        Qt.NoButton, Qt.NoModifier,
        Qt.NoScrollPhase, False,
    )
    timeline.wheelEvent(ev)
    assert timeline.zoom_factor() == 1.0
