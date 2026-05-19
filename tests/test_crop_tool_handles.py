"""CropTool 8-핸들 — 초기 드래그 이후 모서리·가장자리 핸들로 정밀 조정."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w, h):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    return img


def _setup(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.crop import CropTool
    stack = LayerStack(QSize(200, 150))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(200, 150)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = CropTool()
    canvas.set_tool(tool)
    return canvas, tool


def _drag(tool, scene, p1, p2):
    tool.mouse_press(scene, QPointF(*p1))
    tool.mouse_move(scene, QPointF(*p2))
    tool.mouse_release(scene, QPointF(*p2))


def test_handles_appear_after_initial_drag(qtbot):
    """초기 드래그 후 8개 핸들이 scene 에 등장."""
    canvas, tool = _setup(qtbot)
    _drag(tool, canvas.scene(), (20, 20), (80, 60))
    assert len(tool._handles) == 8


def test_corner_handle_drag_resizes_one_corner(qtbot):
    """우하단(SE) 핸들 드래그 — 좌상단 보존, 우하단만 이동."""
    canvas, tool = _setup(qtbot)
    _drag(tool, canvas.scene(), (20, 20), (80, 60))
    # SE 핸들 위치 (80, 60) 잡고 +20, +10 이동.
    tool.mouse_press(canvas.scene(), QPointF(80, 60))
    tool.mouse_move(canvas.scene(), QPointF(100, 70))
    tool.mouse_release(canvas.scene(), QPointF(100, 70))
    r = tool.current_rect()
    assert r.x() == 20 and r.y() == 20
    assert r.width() == 80 and r.height() == 50


def test_edge_handle_drag_moves_only_that_edge(qtbot):
    """가장자리(N) 핸들 드래그 — 상단 변만 이동, 좌우 변·하단 그대로."""
    canvas, tool = _setup(qtbot)
    _drag(tool, canvas.scene(), (20, 20), (80, 60))
    # 상단 중앙 (50, 20) 잡고 +0, +10 (아래로) 이동 → top=30.
    tool.mouse_press(canvas.scene(), QPointF(50, 20))
    tool.mouse_move(canvas.scene(), QPointF(50, 30))
    tool.mouse_release(canvas.scene(), QPointF(50, 30))
    r = tool.current_rect()
    assert r.x() == 20 and r.width() == 60   # 좌·우 변 그대로
    assert r.y() == 30 and r.height() == 30  # top 만 +10, bottom 그대로


def test_inside_drag_translates_rect(qtbot):
    """빈 곳(rect 내부) 드래그 — rect 전체가 평행 이동."""
    canvas, tool = _setup(qtbot)
    _drag(tool, canvas.scene(), (20, 20), (80, 60))
    # 내부 (50, 40) 잡고 +30, +20 이동.
    tool.mouse_press(canvas.scene(), QPointF(50, 40))
    tool.mouse_move(canvas.scene(), QPointF(80, 60))
    tool.mouse_release(canvas.scene(), QPointF(80, 60))
    r = tool.current_rect()
    assert r.x() == 50 and r.y() == 40   # +30, +20
    assert r.width() == 60 and r.height() == 40   # 크기 그대로
