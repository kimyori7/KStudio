"""TimelineSliderLane 위젯 단위 테스트."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest

from screen_recorder.ui.video.timeline import TimelineSliderLane


@pytest.fixture
def lane(qtbot):
    w = TimelineSliderLane()
    qtbot.addWidget(w)
    w.resize(456, 24)   # 56 헤더 + 400 본체
    w.set_duration_ms(10_000)
    return w


def test_header_width_matches_effect_lane(lane):
    """슬라이더 본체 시작 x 좌표는 EffectLane 의 헤더 폭(56)과 동일해야 함."""
    from screen_recorder.ui.video.effect_lane import _HEADER_WIDTH
    assert lane.header_width() == _HEADER_WIDTH


def test_pixel_for_ms_zero_at_header_edge(lane):
    """ms=0 은 헤더 끝(56px)에 위치."""
    assert lane._pixel_for_ms(0) == lane.header_width()


def test_pixel_for_ms_full_at_right_edge(lane):
    """ms=duration 은 위젯 오른쪽 끝(width-1)에 위치."""
    px = lane._pixel_for_ms(10_000)
    assert px >= lane.width() - 2   # 라운딩 1px 허용


def test_click_in_body_emits_seek_request(lane, qtbot):
    """본체 클릭 → 그 ms 위치로 seek 시그널."""
    body_mid_x = lane.header_width() + (lane.width() - lane.header_width()) // 2
    with qtbot.waitSignal(lane.seek_request, timeout=500) as blocker:
        QTest.mouseClick(lane, Qt.LeftButton, pos=QPoint(body_mid_x, lane.height() // 2))
    assert abs(blocker.args[0] - 5_000) <= 100


def test_click_on_header_does_not_emit_seek(lane, qtbot):
    """헤더 영역(0~56) 클릭은 시크 안 함."""
    with qtbot.assertNotEmitted(lane.seek_request, wait=200):
        QTest.mouseClick(lane, Qt.LeftButton, pos=QPoint(20, lane.height() // 2))


def test_set_position_ms_updates_internal_state(lane):
    lane.set_position_ms(3_000)
    assert lane.position_ms() == 3_000
