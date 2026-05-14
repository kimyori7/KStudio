"""SelectionTool + SelectionOverlay — 사각형 영역 선택 + marching-ants 시각화."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w, h):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    return img


def _setup(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.selection import SelectionModel
    from image_editor.tools.selection import SelectionTool
    stack = LayerStack(QSize(100, 80))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(100, 80)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    model = SelectionModel()
    canvas.attach_selection(model)
    tool = SelectionTool(model)
    canvas.set_tool(tool)
    return canvas, model, tool


def test_drag_creates_selection(qtbot):
    """드래그 → SelectionModel.rect 가 그 영역으로 설정."""
    canvas, model, tool = _setup(qtbot)
    tool.mouse_press(canvas.scene(), QPointF(10, 10))
    tool.mouse_move(canvas.scene(), QPointF(40, 30))
    tool.mouse_release(canvas.scene(), QPointF(40, 30))
    r = model.rect()
    assert r is not None
    assert r.x() == 10 and r.y() == 10
    assert r.width() == 30 and r.height() == 20


def test_tiny_drag_does_not_create_selection(qtbot):
    """2px 미만 드래그는 selection 으로 인정 안 함 (오클릭 방어)."""
    canvas, model, tool = _setup(qtbot)
    tool.mouse_press(canvas.scene(), QPointF(10, 10))
    tool.mouse_release(canvas.scene(), QPointF(10, 10))
    assert model.has_selection() is False


def test_escape_clears_selection(qtbot):
    canvas, model, tool = _setup(qtbot)
    model.set_rect(QRect(5, 5, 30, 20))
    tool.key_escape(canvas.scene())
    assert model.has_selection() is False


def test_handle_drag_resizes_selection(qtbot):
    """기존 selection 모서리 핸들을 잡아 끌면 해당 모서리만 이동."""
    canvas, model, tool = _setup(qtbot)
    model.set_rect(QRect(20, 20, 30, 30))   # 50, 50 우하단
    # 우하단 모서리(50, 50)를 잡아 +10, +5 이동.
    tool.mouse_press(canvas.scene(), QPointF(50, 50))
    tool.mouse_move(canvas.scene(), QPointF(60, 55))
    tool.mouse_release(canvas.scene(), QPointF(60, 55))
    r = model.rect()
    assert r is not None
    # 좌상단 그대로, 우하단만 이동 — 40×35.
    assert r.x() == 20 and r.y() == 20
    assert r.width() == 40 and r.height() == 35


def test_overlay_creates_items_when_rect_set(qtbot):
    """SelectionOverlay 가 model 의 rect 가 생기는 즉시 scene 에 아이템을 올린다."""
    canvas, model, _tool = _setup(qtbot)
    # 초기엔 비어 있음.
    items_before = [it for it in canvas.scene().items()
                    if it.zValue() >= 99_999]
    assert items_before == []
    model.set_rect(QRect(10, 10, 30, 20))
    items_after = [it for it in canvas.scene().items()
                   if it.zValue() >= 99_999]
    # 흰 실선 + 검정 점선 두 아이템.
    assert len(items_after) == 2


def test_overlay_removes_items_when_cleared(qtbot):
    canvas, model, _tool = _setup(qtbot)
    model.set_rect(QRect(10, 10, 30, 20))
    model.clear()
    items = [it for it in canvas.scene().items() if it.zValue() >= 99_999]
    assert items == []
