"""TrimMarkerLane — TrimLane 상속 + 헤더(56px) 추가."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from screen_recorder.ui.video.timeline import TrimMarkerLane
from screen_recorder.ui.video.effect_lane import _HEADER_WIDTH


@pytest.fixture
def lane(qtbot):
    w = TrimMarkerLane()
    qtbot.addWidget(w)
    w.resize(456, 36)   # 56 헤더 + 400 본체
    w.set_duration_ms(10_000)
    return w


def test_header_left_pad_matches_effect_lane(lane):
    """본체 시작 x 좌표 = 56."""
    assert lane._lane_left_pad() == _HEADER_WIDTH


def test_pixel_for_ms_zero_at_header_edge(lane):
    """ms=0 은 헤더 끝(56) 에 위치."""
    assert lane._pixel_for_ms(0) == _HEADER_WIDTH


def test_set_in_out_drag_emits_signal(lane, qtbot):
    """[ 핸들 드래그 → in_changed emit (TrimLane 베이스 동작 보존)."""
    lane.set_in_ms(2_000)
    in_px = lane._pixel_for_ms(2_000)
    target_px = lane._pixel_for_ms(4_000)
    with qtbot.waitSignal(lane.in_changed, timeout=1000):
        QTest.mousePress(lane, Qt.LeftButton, pos=QPoint(in_px, lane.height() // 2))
        QTest.mouseMove(lane, pos=QPoint(target_px, lane.height() // 2))
        QTest.mouseRelease(lane, Qt.LeftButton, pos=QPoint(target_px, lane.height() // 2))
    assert abs(lane.in_ms() - 4_000) <= 100


def test_filmstrip_api_inherited(lane):
    """set_filmstrip / has_filmstrip 동일 동작."""
    assert lane.has_filmstrip() is False
    img = QImage(64, 32, QImage.Format_RGB32)
    img.fill(0xFF0000)
    lane.set_filmstrip([img, img])
    assert lane.has_filmstrip() is True


def test_header_click_does_not_seek(lane, qtbot):
    """헤더(0~56) 클릭은 시크/마크 안 함."""
    lane.set_in_ms(2_000)
    lane.set_out_ms(8_000)
    with qtbot.assertNotEmitted(lane.seek_request, wait=200):
        QTest.mouseClick(lane, Qt.LeftButton, pos=QPoint(20, lane.height() // 2))
