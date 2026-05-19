"""SpeedLane — 막대 그리기 + ▶▶ N× 라벨 + 클릭 선택."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt, QPoint

from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.ui.video.speed_lane import SpeedLane


def _lane_with_one_speed(qtbot, in_ms=2000, out_ms=4000, rate=2.0):
    lane = SpeedLane(effect_type="speed", header_label="배속", color="#8b5cf6")
    qtbot.addWidget(lane)
    lane.resize(400, 20)   # 헤더 56px + 본체 344px
    lane.set_duration_ms(10_000)
    eff = SpeedEffect(in_ms=in_ms, out_ms=out_ms, rate=rate)
    lane.set_effects([eff])
    return lane, eff


def test_speed_lane_paints_without_crashing(qtbot):
    """막대 1개 + 라벨 ▶▶ 2× 그리기 — paintEvent 가 예외 없이 통과."""
    lane, _ = _lane_with_one_speed(qtbot, rate=2.0)
    lane.show()
    qtbot.waitExposed(lane)


def test_speed_lane_starts_with_no_selection(qtbot):
    lane, _ = _lane_with_one_speed(qtbot)
    assert lane.selected_id() is None


def test_left_click_on_bar_emits_effect_selected(qtbot):
    """막대 중앙 좌클릭 → effect_selected(eff) 발화."""
    lane, eff = _lane_with_one_speed(qtbot, in_ms=2000, out_ms=4000)
    bar_x = 56 + int(344 * 3000 / 10_000)
    with qtbot.waitSignal(lane.effect_selected, timeout=1000) as blocker:
        qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(bar_x, 10))
    selected = blocker.args[0]
    assert selected.id == eff.id
    assert lane.selected_id() == eff.id


def test_left_click_outside_bar_clears_selection(qtbot):
    lane, eff = _lane_with_one_speed(qtbot, in_ms=2000, out_ms=4000)
    bar_x = 56 + int(344 * 3000 / 10_000)
    qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(bar_x, 10))
    outside_x = 56 + int(344 * 8000 / 10_000)
    qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(outside_x, 10))
    assert lane.selected_id() is None


def test_two_speed_effects_each_selectable(qtbot):
    """서로 다른 시간대의 두 SpeedEffect — 각각 클릭 시 자기만 선택."""
    lane = SpeedLane(effect_type="speed", header_label="배속", color="#8b5cf6")
    qtbot.addWidget(lane)
    lane.resize(400, 20)
    lane.set_duration_ms(10_000)
    a = SpeedEffect(in_ms=1000, out_ms=3000, rate=2.0)
    b = SpeedEffect(in_ms=5000, out_ms=8000, rate=0.5)
    lane.set_effects([a, b])

    # a 막대 중앙 (2000ms 위치) 클릭
    a_x = 56 + int(344 * 2000 / 10_000)
    qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(a_x, 10))
    assert lane.selected_id() == a.id

    # b 막대 중앙 (6500ms 위치) 클릭
    b_x = 56 + int(344 * 6500 / 10_000)
    qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(b_x, 10))
    assert lane.selected_id() == b.id


def test_drag_bar_emits_effect_changed_with_new_time(qtbot):
    """막대를 +500ms 만큼 우측으로 드래그 → effect_changed 발화."""
    lane, eff = _lane_with_one_speed(qtbot, in_ms=2000, out_ms=4000)
    start_x = 56 + int(344 * 3000 / 10_000)
    delta_px = int(344 * 500 / 10_000)

    received: list = []
    lane.effect_changed.connect(received.append)

    qtbot.mousePress(lane, Qt.LeftButton, pos=QPoint(start_x, 10))
    qtbot.mouseMove(lane, QPoint(start_x + delta_px, 10))
    qtbot.mouseRelease(lane, Qt.LeftButton, pos=QPoint(start_x + delta_px, 10))

    assert len(received) >= 1
    last = received[-1]
    assert 2300 < last.in_ms < 2700
    assert last.out_ms - last.in_ms == 2000   # 길이 보존


def test_drag_left_past_zero_preserves_width(qtbot):
    """2026-05-19 사용자 보고 회귀: 막대 왼쪽으로 끌어 in_ms 가 0 도달 후에도 더 끌면
    out_ms 가 줄어 폭이 좁아짐. fix 후엔 0 에서 멈추고 폭(2000ms) 보존.
    """
    lane, eff = _lane_with_one_speed(qtbot, in_ms=2000, out_ms=4000)
    start_x = 56 + int(344 * 3000 / 10_000)
    # 영상 길이 10초 안에서 5000ms 왼쪽으로 끌기 (in 이 -3000 까지 가는 시도).
    delta_px = -int(344 * 5000 / 10_000)

    received: list = []
    lane.effect_changed.connect(received.append)

    qtbot.mousePress(lane, Qt.LeftButton, pos=QPoint(start_x, 10))
    qtbot.mouseMove(lane, QPoint(start_x + delta_px, 10))
    qtbot.mouseRelease(lane, Qt.LeftButton, pos=QPoint(start_x + delta_px, 10))

    assert len(received) >= 1
    last = received[-1]
    assert last.in_ms == 0, f"왼쪽 끝 도달 후 in_ms 는 0 이어야 함 (got {last.in_ms})"
    assert last.out_ms - last.in_ms == 2000, \
        f"폭은 원본 2000ms 보존되어야 함 (got width={last.out_ms - last.in_ms})"


def test_drag_right_past_duration_preserves_width(qtbot):
    """대칭 — 오른쪽 끝 너머로 끌어도 폭 보존."""
    lane, eff = _lane_with_one_speed(qtbot, in_ms=2000, out_ms=4000)
    start_x = 56 + int(344 * 3000 / 10_000)
    # 영상 끝 10000 너머 8000ms 까지 끌기.
    delta_px = int(344 * 8000 / 10_000)

    received: list = []
    lane.effect_changed.connect(received.append)

    qtbot.mousePress(lane, Qt.LeftButton, pos=QPoint(start_x, 10))
    qtbot.mouseMove(lane, QPoint(start_x + delta_px, 10))
    qtbot.mouseRelease(lane, Qt.LeftButton, pos=QPoint(start_x + delta_px, 10))

    assert len(received) >= 1
    last = received[-1]
    assert last.out_ms == 10_000, f"오른쪽 끝 도달 후 out_ms 는 duration (got {last.out_ms})"
    assert last.out_ms - last.in_ms == 2000, \
        f"폭은 원본 2000ms 보존되어야 함 (got width={last.out_ms - last.in_ms})"


def test_delete_key_emits_effect_deleted(qtbot):
    lane, eff = _lane_with_one_speed(qtbot)
    bar_x = 56 + int(344 * 3000 / 10_000)
    qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(bar_x, 10))
    lane.show()
    qtbot.waitExposed(lane)
    lane.setFocus()
    with qtbot.waitSignal(lane.effect_deleted, timeout=1000) as blocker:
        qtbot.keyClick(lane, Qt.Key_Delete)
    assert blocker.args == [eff.id]
