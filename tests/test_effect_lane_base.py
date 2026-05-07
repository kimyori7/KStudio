"""EffectLane 베이스 위젯."""
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QWidget

from screen_recorder.ui.video.effect_lane import EffectLane


def test_lane_default_state(qtbot):
    lane = EffectLane(effect_type="caption", header_label="캡션", color="#3b82f6")
    qtbot.addWidget(lane)
    assert lane.effect_type() == "caption"
    assert lane.header_label() == "캡션"
    assert lane.color_hex() == "#3b82f6"
    # 기본 높이 ~ 20px (콤팩트)
    assert 16 <= lane.height() <= 32


def test_lane_set_duration_and_position(qtbot):
    lane = EffectLane(effect_type="caption", header_label="캡션", color="#3b82f6")
    qtbot.addWidget(lane)
    lane.set_duration_ms(10_000)
    lane.set_position_ms(2_500)
    assert lane.duration_ms() == 10_000
    assert lane.position_ms() == 2_500


def test_lane_right_click_emits_request_with_time(qtbot):
    """lane 의 빈 영역 우클릭 → request_add_at(ms) 시그널."""
    lane = EffectLane(effect_type="caption", header_label="캡션", color="#3b82f6")
    qtbot.addWidget(lane)
    lane.resize(400, 20)
    lane.set_duration_ms(10_000)
    # 우클릭 위치: 가운데 (5_000ms 근처)
    with qtbot.waitSignal(lane.request_add_at, timeout=1000) as blocker:
        qtbot.mouseClick(lane, Qt.RightButton, pos=QPoint(200, 10))
    ms = blocker.args[0]
    assert 4_000 <= ms <= 6_000  # 위치-시간 변환 정확성


def test_lane_left_click_no_signal_when_no_effects(qtbot):
    """효과가 없으면 좌클릭은 시그널 없음 (효과 추가는 우클릭으로만)."""
    lane = EffectLane(effect_type="caption", header_label="캡션", color="#3b82f6")
    qtbot.addWidget(lane)
    lane.resize(400, 20)
    lane.set_duration_ms(10_000)
    received_select: list = []
    lane.effect_selected.connect(received_select.append)
    qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(200, 10))
    assert received_select == []


def test_lane_paint_does_not_crash_with_zero_duration(qtbot):
    """duration=0 일 때 paint 호출이 ZeroDivision 으로 죽지 않아야."""
    lane = EffectLane(effect_type="caption", header_label="캡션", color="#3b82f6")
    qtbot.addWidget(lane)
    lane.show()  # paint event 트리거
    qtbot.waitExposed(lane)
    # 단순히 죽지 않으면 통과 (paint 가 호출됨)
