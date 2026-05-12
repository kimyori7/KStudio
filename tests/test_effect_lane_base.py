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


def test_lane_right_click_shows_context_menu(qtbot):
    """lane 우클릭 → 컨텍스트 메뉴 (효과 추가 / 라인 지우기). Phase 28."""
    lane = EffectLane(effect_type="caption", header_label="캡션", color="#3b82f6")
    qtbot.addWidget(lane)
    lane.resize(400, 20)
    lane.set_duration_ms(10_000)
    # 우클릭 → _show_lane_context_menu 호출 (메뉴 popup, non-blocking).
    # 메뉴 action 직접 trigger 로 효과 추가 시그널 확인.
    lane._show_lane_context_menu(5_000, QPoint(0, 0))
    # popup 직후 active widget 검색 — Qt 의 QMenu 가 self 의 자식으로 떠 있음.
    from PySide6.QtWidgets import QMenu
    menus = lane.findChildren(QMenu)
    assert menus, "context menu 가 떠야 한다"
    add_action = next((a for a in menus[0].actions() if "추가" in a.text()), None)
    assert add_action is not None
    with qtbot.waitSignal(lane.request_add_at, timeout=500) as blocker:
        add_action.trigger()
    assert blocker.args == [5_000]


def test_lane_context_menu_remove_emits_remove_signal(qtbot):
    """lane 우클릭 메뉴의 '이 라인 지우기' → request_remove_lane 시그널."""
    lane = EffectLane(effect_type="caption", header_label="캡션", color="#3b82f6")
    qtbot.addWidget(lane)
    lane.resize(400, 20)
    lane.set_duration_ms(10_000)
    lane._show_lane_context_menu(3_000, QPoint(0, 0))
    from PySide6.QtWidgets import QMenu
    menus = lane.findChildren(QMenu)
    remove_action = next((a for a in menus[0].actions() if "지우기" in a.text()), None)
    assert remove_action is not None
    with qtbot.waitSignal(lane.request_remove_lane, timeout=500):
        remove_action.trigger()


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
