"""ZoomLane — 막대 그리기 + ⊕ N× 라벨 + 클릭 선택."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt, QPoint

from screen_recorder.effects.types.zoom import ZoomEffect, ZoomPoint
from screen_recorder.ui.video.zoom_lane import ZoomLane


def _lane_with_one_zoom(qtbot, in_ms=2000, out_ms=4000, scale=2.5,
                         cx=0.5, cy=0.5):
    lane = ZoomLane(effect_type="zoom", header_label="줌", color="#10b981")
    qtbot.addWidget(lane)
    lane.resize(400, 20)   # 헤더 56px + 본체 344px
    lane.set_duration_ms(10_000)
    pt = ZoomPoint(cx=cx, cy=cy, scale=scale)
    eff = ZoomEffect(in_ms=in_ms, out_ms=out_ms, start=pt, end=pt)
    lane.set_effects([eff])
    return lane, eff


def test_renders_zoom_label(qtbot):
    """막대 1개 + ⊕ 2.5× 라벨 그리기 — paintEvent 가 예외 없이 통과."""
    lane, _ = _lane_with_one_zoom(qtbot, scale=2.5)
    lane.show()
    qtbot.waitExposed(lane)


def test_lane_starts_with_no_selection(qtbot):
    lane, _ = _lane_with_one_zoom(qtbot)
    assert lane.selected_id() is None


def test_click_on_bar_emits_selected(qtbot):
    """막대 중앙 좌클릭 → effect_selected(eff) 발화."""
    lane, eff = _lane_with_one_zoom(qtbot, in_ms=2000, out_ms=4000)
    bar_x = 56 + int(344 * 3000 / 10_000)
    with qtbot.waitSignal(lane.effect_selected, timeout=1000) as blocker:
        qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(bar_x, 10))
    selected = blocker.args[0]
    assert selected.id == eff.id
    assert lane.selected_id() == eff.id


def test_click_outside_bar_clears_selection(qtbot):
    lane, eff = _lane_with_one_zoom(qtbot, in_ms=2000, out_ms=4000)
    bar_x = 56 + int(344 * 3000 / 10_000)
    qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(bar_x, 10))
    outside_x = 56 + int(344 * 8000 / 10_000)
    qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(outside_x, 10))
    assert lane.selected_id() is None


def test_drag_bar_emits_effect_changed_with_new_time(qtbot):
    """막대를 +500ms 만큼 우측으로 드래그 → effect_changed 발화."""
    lane, eff = _lane_with_one_zoom(qtbot, in_ms=2000, out_ms=4000)
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


def test_delete_key_emits_effect_deleted(qtbot):
    lane, eff = _lane_with_one_zoom(qtbot)
    bar_x = 56 + int(344 * 3000 / 10_000)
    qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(bar_x, 10))
    lane.show()
    qtbot.waitExposed(lane)
    lane.setFocus()
    with qtbot.waitSignal(lane.effect_deleted, timeout=1000) as blocker:
        qtbot.keyClick(lane, Qt.Key_Delete)
    assert blocker.args == [eff.id]
