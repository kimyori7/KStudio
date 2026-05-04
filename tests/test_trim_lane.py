"""TrimLane 위젯 단위 테스트."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest

from screen_recorder.ui.video.trim_lane import TrimLane


@pytest.fixture
def lane(qtbot):
    w = TrimLane()
    qtbot.addWidget(w)
    w.resize(400, 32)
    w.set_duration_ms(10_000)
    return w


def test_pixel_for_ms_maps_correctly(lane):
    """위치 계산 — duration 10초, lane 폭 400px: 5초 → 200px (절반)."""
    assert lane._pixel_for_ms(0) == lane._lane_left_pad()
    mid_px = lane._pixel_for_ms(5_000)
    expected = lane._lane_left_pad() + (lane.width() - lane._lane_left_pad() - lane._lane_right_pad()) // 2
    assert abs(mid_px - expected) <= 1


def test_ms_for_pixel_inverse(lane):
    """ms→px→ms 라운드트립 — duration 10초 / 400px / 5000ms 위치는 ±50ms 오차 안."""
    px = lane._pixel_for_ms(5_000)
    back = lane._ms_for_pixel(px)
    assert abs(back - 5_000) <= 50


def test_set_in_ms_emits_no_signal_for_programmatic_call(lane, qtbot):
    """프로그래매틱 set_in_ms 는 in_changed 를 발화하지 않는다."""
    with qtbot.assertNotEmitted(lane.in_changed, wait=100):
        lane.set_in_ms(2_000)
    assert lane.in_ms() == 2_000


def test_set_out_below_in_returns_unswapped(lane):
    """TrimLane 자체는 swap 하지 않음 — 부모 책임."""
    lane.set_in_ms(5_000)
    lane.set_out_ms(2_000)
    assert lane.in_ms() == 5_000
    assert lane.out_ms() == 2_000


def test_clear_resets_handles(lane):
    lane.set_in_ms(2_000)
    lane.set_out_ms(8_000)
    lane.clear()
    assert lane.in_ms() is None
    assert lane.out_ms() is None


def test_mouse_drag_on_in_handle_emits_in_changed(lane, qtbot):
    """[ 핸들 클릭 → 끌어서 떼면 in_changed 가 emit, 마지막 값이 4초 근처."""
    lane.set_in_ms(2_000)
    in_px = lane._pixel_for_ms(2_000)
    target_px = lane._pixel_for_ms(4_000)

    with qtbot.waitSignal(lane.in_changed, timeout=1000):
        QTest.mousePress(lane, Qt.LeftButton, pos=QPoint(in_px, lane.height() // 2))
        QTest.mouseMove(lane, pos=QPoint(target_px, lane.height() // 2))
        QTest.mouseRelease(lane, Qt.LeftButton, pos=QPoint(target_px, lane.height() // 2))

    assert abs(lane.in_ms() - 4_000) <= 100


def test_mouse_drag_emits_seek_request(lane, qtbot):
    """드래그 중 seek_request 도 같이 emit (영상 실시간 스크럽)."""
    lane.set_in_ms(2_000)
    in_px = lane._pixel_for_ms(2_000)
    with qtbot.waitSignal(lane.seek_request, timeout=1000):
        QTest.mousePress(lane, Qt.LeftButton, pos=QPoint(in_px, lane.height() // 2))
        QTest.mouseRelease(lane, Qt.LeftButton, pos=QPoint(in_px, lane.height() // 2))


def test_empty_space_click_seeks_without_changing_handles(lane, qtbot):
    """핸들 외 빈 공간 클릭 = 시크. in/out 은 안 건드림."""
    lane.set_in_ms(2_000)
    lane.set_out_ms(8_000)
    target_px = lane._pixel_for_ms(5_000)   # 5초 위치 — in/out 둘 다 멀리 떨어짐

    with qtbot.waitSignal(lane.seek_request, timeout=1000) as blocker:
        with qtbot.assertNotEmitted(lane.in_changed, wait=200):
            with qtbot.assertNotEmitted(lane.out_changed, wait=200):
                QTest.mousePress(lane, Qt.LeftButton, pos=QPoint(target_px, lane.height() // 2))
                QTest.mouseRelease(lane, Qt.LeftButton, pos=QPoint(target_px, lane.height() // 2))
    assert abs(blocker.args[0] - 5_000) <= 100
    # in/out 변경 안 됨
    assert lane.in_ms() == 2_000
    assert lane.out_ms() == 8_000
