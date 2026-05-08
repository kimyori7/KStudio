"""BrollLane — 막대 그리기 + 🎞 파일명 라벨 + 클릭 선택."""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint

from screen_recorder.effects.types.broll import BrollEffect, PipConfig
from screen_recorder.ui.video.broll_lane import BrollLane


def _lane_with_one_broll(qtbot, in_ms=2000, out_ms=4000, src="myclip.mp4"):
    lane = BrollLane(effect_type="broll", header_label="곁들임 영상", color="#f59e0b")
    qtbot.addWidget(lane)
    lane.resize(400, 20)   # 헤더 56px + 본체 344px
    lane.set_duration_ms(10_000)
    eff = BrollEffect(
        in_ms=in_ms, out_ms=out_ms, src=src, placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
    )
    lane.set_effects([eff])
    return lane, eff


def test_renders_broll_label(qtbot):
    """막대 1개 + 🎞 파일명 라벨 그리기 — paintEvent 가 예외 없이 통과."""
    lane, _ = _lane_with_one_broll(qtbot, src="myclip.mp4")
    lane.show()
    qtbot.waitExposed(lane)


def test_renders_broll_label_with_empty_src(qtbot):
    """src 가 비어 있으면 '?' 라벨 — paintEvent 가 예외 없이 통과."""
    lane, _ = _lane_with_one_broll(qtbot, src="")
    lane.show()
    qtbot.waitExposed(lane)


def test_click_on_bar_emits_selected(qtbot):
    """막대 중앙 좌클릭 → effect_selected(eff) 발화."""
    lane, eff = _lane_with_one_broll(qtbot, in_ms=2000, out_ms=4000)
    bar_x = 56 + int(344 * 3000 / 10_000)
    with qtbot.waitSignal(lane.effect_selected, timeout=1000) as blocker:
        qtbot.mouseClick(lane, Qt.LeftButton, pos=QPoint(bar_x, 10))
    selected = blocker.args[0]
    assert selected.id == eff.id
    assert lane.selected_id() == eff.id
