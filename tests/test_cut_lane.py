"""CutLane — 3 시각 모드, hit-test, drag, Delete."""
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
import pytest

from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.ui.video.cut_lane import CutLane


@pytest.fixture
def lane(qtbot):
    w = CutLane(effect_type="cut", header_label="컷", color="#ef4444")
    w.set_duration_ms(20000)
    w.resize(400, 20)
    qtbot.addWidget(w)
    return w


def _splice():
    return CutEffect(in_ms=5000, out_ms=5000, src="x.mp4", src_duration_ms=2000)


def _range_no_insert():
    return CutEffect(in_ms=4000, out_ms=8000)


def _range_with_insert():
    return CutEffect(in_ms=4000, out_ms=8000, src="x.mp4", src_in_ms=0, src_out_ms=3000, src_duration_ms=3000)


def test_lane_renders_three_modes_without_error(lane, qtbot):
    """세 효과를 한꺼번에 set_effects 해도 paint 가 예외 없이 끝난다."""
    lane.set_effects([_splice(), _range_no_insert(), _range_with_insert()])
    lane.repaint()  # paintEvent 강제 트리거
    qtbot.wait(10)


def test_hit_test_splice_treats_as_marker(lane):
    """splice point 는 폭 0 인데 ±5px 안을 hit 로 인정해야 잡을 수 있다."""
    lane.set_effects([_splice()])
    splice = lane._effects[0]
    x_center = lane._ms_to_x(splice.in_ms)
    eff, kind = lane._hit_test(x_center)
    assert eff is not None
    assert eff.id == splice.id


def test_hit_test_range_returns_move_in_middle(lane):
    lane.set_effects([_range_no_insert()])
    e = lane._effects[0]
    x_mid = (lane._ms_to_x(e.in_ms) + lane._ms_to_x(e.out_ms)) // 2
    eff, kind = lane._hit_test(x_mid)
    assert eff is not None
    assert kind == "move"


def test_hit_test_range_returns_left_edge(lane):
    lane.set_effects([_range_no_insert()])
    e = lane._effects[0]
    x = lane._ms_to_x(e.in_ms) + 1
    eff, kind = lane._hit_test(x)
    assert kind == "left"


def test_delete_emits_signal(lane, qtbot):
    e = _range_with_insert()
    lane.set_effects([e])
    lane._selected_id = e.id
    lane.setFocus()
    with qtbot.waitSignal(lane.effect_deleted) as sig:
        qtbot.keyClick(lane, Qt.Key_Delete)
    assert sig.args == [e.id]


def test_drag_move_emits_changed(lane, qtbot):
    e = _range_no_insert()
    lane.set_effects([e])
    x_start = (lane._ms_to_x(e.in_ms) + lane._ms_to_x(e.out_ms)) // 2
    # 좌클릭 → 드래그 → 릴리즈. PySide 이벤트 흐름.
    press = QMouseEvent(QEvent.MouseButtonPress, QPointF(x_start, 10), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    move = QMouseEvent(QEvent.MouseMove, QPointF(x_start + 40, 10), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    release = QMouseEvent(QEvent.MouseButtonRelease, QPointF(x_start + 40, 10), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    with qtbot.waitSignal(lane.effect_changed) as sig:
        lane.mousePressEvent(press)
        lane.mouseMoveEvent(move)
        lane.mouseReleaseEvent(release)   # release 에서 effect_changed 발화
    new_eff = sig.args[0]
    assert new_eff.id == e.id
    assert new_eff.in_ms > e.in_ms  # 오른쪽으로 이동


def test_double_click_emits_selected(lane, qtbot):
    """더블클릭 시 effect_selected 가 한 번 더 발화 — 인스펙터 포커스용."""
    e = _range_with_insert()
    lane.set_effects([e])
    x = (lane._ms_to_x(e.in_ms) + lane._ms_to_x(e.out_ms)) // 2
    dbl = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(x, 10), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    with qtbot.waitSignal(lane.effect_selected) as sig:
        lane.mouseDoubleClickEvent(dbl)
    assert sig.args[0].id == e.id
