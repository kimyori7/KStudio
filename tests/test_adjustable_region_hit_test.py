"""AdjustableRegionBorder._hit_test — 코너/에지/이동 판정.

상단 코너(nw/ne)도 대각선 리사이즈로 동작해야 한다 (타이틀바 이동보다 우선).
하단 코너(sw/se)·에지·녹화 중 잠금은 회귀 보호.
상단 코너 드래그 결과(geometry)는 이번에 새로 살아난 경로라 별도로 검증.
"""
from PySide6.QtCore import QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import Qt
import pytest

from screen_recorder.ui.overlay.adjustable_region import AdjustableRegionBorder


@pytest.fixture
def border(qtbot):
    w = AdjustableRegionBorder((100, 100, 400, 300), mode="video")
    qtbot.addWidget(w)
    return w


def _hit(border, x, y):
    return border._hit_test(QPoint(x, y))


def test_top_left_corner_is_nw_resize(border):
    assert _hit(border, 5, 5) == "nw"


def test_top_right_corner_is_ne_resize(border):
    w = border.width()
    assert _hit(border, w - 5, 5) == "ne"


def test_bottom_corners_still_resize(border):
    w, h = border.width(), border.height()
    assert _hit(border, 5, h - 5) == "sw"
    assert _hit(border, w - 5, h - 5) == "se"


def test_title_bar_middle_is_move(border):
    # 코너를 벗어난 타이틀바 가운데는 여전히 이동.
    assert _hit(border, border.width() // 2, 5) == "move"


def test_side_and_bottom_edges_resize(border):
    w, h = border.width(), border.height()
    assert _hit(border, 3, h // 2) == "w"
    assert _hit(border, w - 3, h // 2) == "e"
    assert _hit(border, w // 2, h - 3) == "s"


def test_recording_locks_size_everywhere(border):
    # 녹화 중에는 코너까지 전부 이동만 (인코더 입력 해상도 고정).
    border._state = "recording"
    w, h = border.width(), border.height()
    assert _hit(border, 5, 5) == "move"
    assert _hit(border, w - 5, 5) == "move"
    assert _hit(border, 5, h - 5) == "move"
    assert _hit(border, w - 5, h - 5) == "move"


def _drag(border, local_x, local_y, dx, dy):
    """local(x,y) 에서 press → (dx,dy) 만큼 이동. press/move 핸들러 직접 호출."""
    g0x, g0y = 1000, 1000  # 임의의 글로벌 기준점 (delta 만 의미 있음)
    press = QMouseEvent(
        QEvent.MouseButtonPress, QPointF(local_x, local_y), QPointF(g0x, g0y),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    border.mousePressEvent(press)
    move = QMouseEvent(
        QEvent.MouseMove, QPointF(local_x + dx, local_y + dy), QPointF(g0x + dx, g0y + dy),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
    )
    border.mouseMoveEvent(move)


def test_nw_drag_moves_top_left_and_shrinks(border):
    # 좌상단을 +40,+30 끌면: 좌·상 경계가 그만큼 들어와 크기가 줄어든다.
    x0, y0, w0, h0 = border.x(), border.y(), border.width(), border.height()
    _drag(border, 5, 5, 40, 30)
    assert border.x() == x0 + 40
    assert border.y() == y0 + 30
    assert border.width() == w0 - 40
    assert border.height() == h0 - 30


def test_ne_drag_grows_width_and_moves_top(border):
    # 우상단을 +40,+30 끌면: 우 경계는 늘고(폭+40), 상 경계는 내려와(높이-30), x 는 고정.
    x0, y0, w0, h0 = border.x(), border.y(), border.width(), border.height()
    _drag(border, border.width() - 5, 5, 40, 30)
    assert border.x() == x0
    assert border.y() == y0 + 30
    assert border.width() == w0 + 40
    assert border.height() == h0 - 30
