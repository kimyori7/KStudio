"""CaptionLane — 막대 그리기·선택·드래그·삭제."""
import pytest
from PySide6.QtCore import Qt, QPoint

from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.ui.video.caption_lane import CaptionLane


def _lane_with_one_caption(qtbot, in_ms=2000, out_ms=4000):
    lane = CaptionLane(effect_type="caption", header_label="캡션", color="#3b82f6")
    qtbot.addWidget(lane)
    lane.resize(400, 20)   # 헤더 56px + 본체 344px
    lane.set_duration_ms(10_000)
    cap = CaptionEffect(in_ms=in_ms, out_ms=out_ms, text="hi")
    lane.set_effects([cap])
    return lane, cap


def test_caption_lane_starts_with_no_selection(qtbot):
    lane, _ = _lane_with_one_caption(qtbot)
    assert lane.selected_id() is None


def test_left_click_on_bar_selects(qtbot):
    lane, cap = _lane_with_one_caption(qtbot, in_ms=2000, out_ms=4000)
    # 막대 중앙 좌표 = 헤더(56) + (3000ms / 10000ms) * 344 ≈ 56 + 103 = 159
    bar_x = 56 + int(344 * 3000 / 10_000)
    with qtbot.waitSignal(lane.effect_selected, timeout=1000) as blocker:
        qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(bar_x, 10))
    selected = blocker.args[0]
    assert selected.id == cap.id
    assert lane.selected_id() == cap.id


def test_left_click_outside_bar_clears_selection(qtbot):
    lane, cap = _lane_with_one_caption(qtbot, in_ms=2000, out_ms=4000)
    # 먼저 선택
    bar_x = 56 + int(344 * 3000 / 10_000)
    qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(bar_x, 10))
    # 막대 밖 (8000ms 위치) 클릭
    outside_x = 56 + int(344 * 8000 / 10_000)
    qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(outside_x, 10))
    assert lane.selected_id() is None


def test_drag_bar_emits_effect_changed_with_new_time(qtbot):
    """막대를 +500ms 만큼 우측으로 드래그 → effect_changed 발화."""
    lane, cap = _lane_with_one_caption(qtbot, in_ms=2000, out_ms=4000)
    start_x = 56 + int(344 * 3000 / 10_000)   # 막대 중앙
    delta_px = int(344 * 500 / 10_000)         # 500ms 만큼 px

    received: list = []
    lane.effect_changed.connect(received.append)

    qtbot.mousePress(lane, Qt.LeftButton, pos=QPoint(start_x, 10))
    qtbot.mouseMove(lane, QPoint(start_x + delta_px, 10))
    qtbot.mouseRelease(lane, Qt.LeftButton, pos=QPoint(start_x + delta_px, 10))

    assert len(received) >= 1
    last = received[-1]
    # 약간의 픽셀 오차 허용
    assert 2300 < last.in_ms < 2700
    assert last.out_ms - last.in_ms == 2000   # 길이 보존


def test_drag_right_edge_extends_length(qtbot):
    """막대 우측 끝(out_ms 위치)에서 +500ms 드래그 → 길이만 늘어남."""
    lane, cap = _lane_with_one_caption(qtbot, in_ms=2000, out_ms=4000)
    edge_x = 56 + int(344 * 4000 / 10_000)     # 우측 끝 = 4000ms
    delta_px = int(344 * 500 / 10_000)

    received: list = []
    lane.effect_changed.connect(received.append)

    qtbot.mousePress(lane, Qt.LeftButton, pos=QPoint(edge_x, 10))
    qtbot.mouseMove(lane, QPoint(edge_x + delta_px, 10))
    qtbot.mouseRelease(lane, Qt.LeftButton, pos=QPoint(edge_x + delta_px, 10))

    last = received[-1]
    assert last.in_ms == 2000   # 시작점 그대로
    assert 4300 < last.out_ms < 4700   # +500ms


def test_delete_key_emits_effect_deleted(qtbot):
    lane, cap = _lane_with_one_caption(qtbot)
    bar_x = 56 + int(344 * 3000 / 10_000)
    qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(bar_x, 10))   # select
    lane.show()
    qtbot.waitExposed(lane)
    lane.setFocus()
    with qtbot.waitSignal(lane.effect_deleted, timeout=1000) as blocker:
        qtbot.keyClick(lane, Qt.Key_Delete)
    assert blocker.args == [cap.id]


def test_paint_does_not_crash_with_one_caption(qtbot):
    lane, _ = _lane_with_one_caption(qtbot)
    lane.show()
    qtbot.waitExposed(lane)
