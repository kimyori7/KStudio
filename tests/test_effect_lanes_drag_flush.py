"""모든 드래그형 효과 lane 에서 '이웃에 딱 붙기(flush)' 동작.

2026-06-23: 배속에 이어 캡션·자르기·줌·곁들임·화살표·사각형 lane 도 같은 row 이웃에
겹치게 끌면 원복되던 동작 → 이웃 edge 에 딱 붙도록 통일. 공용 헬퍼
EffectLane._clamp_against_siblings 를 각 lane 의 mouseMoveEvent 가 호출하는지 검증.

hit_test 기하(멀티-row y, splice 등)에 의존하지 않도록 드래그 상태를 직접 세팅하고
합성 MouseMove 이벤트를 mouseMoveEvent 에 보내 move 계산 + 클램프만 본다.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from screen_recorder.effects.types.arrow import ArrowEffect
from screen_recorder.effects.types.broll import BrollEffect
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.effects.types.rect import RectEffect
from screen_recorder.effects.types.zoom import ZoomEffect
from screen_recorder.ui.video.arrow_lane import ArrowLane
from screen_recorder.ui.video.broll_lane import BrollLane
from screen_recorder.ui.video.caption_lane import CaptionLane
from screen_recorder.ui.video.cut_lane import CutLane
from screen_recorder.ui.video.rect_lane import RectLane
from screen_recorder.ui.video.zoom_lane import ZoomLane


def _cap(in_ms, out_ms):
    return CaptionEffect(in_ms=in_ms, out_ms=out_ms, text="x")


def _cut(in_ms, out_ms):
    return CutEffect(in_ms=in_ms, out_ms=out_ms)


def _zoom(in_ms, out_ms):
    return ZoomEffect(in_ms=in_ms, out_ms=out_ms)


def _broll(in_ms, out_ms):
    return BrollEffect(in_ms=in_ms, out_ms=out_ms)


def _arrow(in_ms, out_ms):
    return ArrowEffect(in_ms=in_ms, out_ms=out_ms)


def _rect(in_ms, out_ms):
    return RectEffect(in_ms=in_ms, out_ms=out_ms)


CASES = [
    ("caption", CaptionLane, _cap),
    ("cut", CutLane, _cut),
    ("zoom", ZoomLane, _zoom),
    ("broll", BrollLane, _broll),
    ("arrow", ArrowLane, _arrow),
    ("rect", RectLane, _rect),
]
_IDS = [c[0] for c in CASES]

_DURATION = 10_000
_BODY_W = 344            # resize(400) - header 56


def _ms_to_x(ms: int) -> float:
    return 56 + _BODY_W * ms / _DURATION


def _send_move(lane, x: float) -> None:
    ev = QMouseEvent(QEvent.MouseMove, QPointF(x, 10.0),
                     Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    lane.mouseMoveEvent(ev)


def _setup(qtbot, Lane, name, a, b):
    lane = Lane(effect_type=name, header_label=name, color="#8b5cf6")
    qtbot.addWidget(lane)
    lane.resize(400, 40)
    lane.set_duration_ms(_DURATION)
    lane.set_effects([a, b])
    return lane


@pytest.mark.parametrize("name,Lane,mk", CASES, ids=_IDS)
def test_drag_into_right_neighbor_snaps_flush(qtbot, name, Lane, mk):
    """a 를 우측으로 끌어 b 와 겹치려 함 → b 의 왼쪽 edge(5000)에 딱 붙음(폭 보존)."""
    a = mk(1000, 3000)
    b = mk(5000, 8000)
    lane = _setup(qtbot, Lane, name, a, b)
    # 드래그 상태 직접 세팅 (hit_test 기하 우회).
    lane._drag_id = a.id
    lane._drag_kind = "move"
    lane._drag_start_x = int(_ms_to_x(2000))      # a 중앙
    lane._drag_orig_in = a.in_ms
    lane._drag_orig_out = a.out_ms
    if hasattr(lane, "_drag_track_idx"):
        lane._drag_track_idx = 0

    _send_move(lane, _ms_to_x(2000 + 3500))        # +3500ms → a.out 가 5000 너머로
    last = lane._drag_last_eff
    assert last is not None and last.id == a.id
    assert last.out_ms == 5000, f"{name}: 이웃 edge(5000)에 딱 붙어야 (got {last.out_ms})"
    assert last.out_ms - last.in_ms == 2000, f"{name}: 폭 보존"


@pytest.mark.parametrize("name,Lane,mk", CASES, ids=_IDS)
def test_drag_into_left_neighbor_snaps_flush(qtbot, name, Lane, mk):
    """b 를 좌측으로 끌어 a 와 겹치려 함 → a 의 오른쪽 edge(3000)에 딱 붙음."""
    a = mk(1000, 3000)
    b = mk(5000, 8000)
    lane = _setup(qtbot, Lane, name, a, b)
    lane._drag_id = b.id
    lane._drag_kind = "move"
    lane._drag_start_x = int(_ms_to_x(6500))      # b 중앙
    lane._drag_orig_in = b.in_ms
    lane._drag_orig_out = b.out_ms
    if hasattr(lane, "_drag_track_idx"):
        lane._drag_track_idx = 0

    _send_move(lane, _ms_to_x(6500 - 3500))        # -3500ms → b.in 이 3000 아래로
    last = lane._drag_last_eff
    assert last is not None and last.id == b.id
    assert last.in_ms == 3000, f"{name}: 이웃 edge(3000)에 딱 붙어야 (got {last.in_ms})"
    assert last.out_ms - last.in_ms == 3000, f"{name}: 폭 보존"
