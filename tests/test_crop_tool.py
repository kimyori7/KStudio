"""CropTool — 사각형 오버레이 + Enter 확정/Esc 취소."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w, h):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    return img


def test_activate_shows_overlay_covering_canvas(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.crop import CropTool
    stack = LayerStack(QSize(100, 80))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(100, 80)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = CropTool()
    canvas.set_tool(tool)
    assert tool.current_rect() == QRect(0, 0, 100, 80)


def test_drag_changes_rect(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.crop import CropTool
    stack = LayerStack(QSize(100, 80))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(100, 80)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = CropTool()
    canvas.set_tool(tool)
    tool.mouse_press(canvas.scene(), QPointF(20, 10))
    tool.mouse_move(canvas.scene(), QPointF(60, 50))
    tool.mouse_release(canvas.scene(), QPointF(60, 50))
    r = tool.current_rect()
    assert r.x() == 20 and r.y() == 10
    assert r.width() == 40 and r.height() == 40


def test_commit_emits_signal_with_rect(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.crop import CropTool
    stack = LayerStack(QSize(100, 80))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(100, 80)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = CropTool()
    canvas.set_tool(tool)
    tool.mouse_press(canvas.scene(), QPointF(10, 10))
    tool.mouse_release(canvas.scene(), QPointF(40, 40))
    # Emulate user pressing Enter on the canvas — the canvas forwards via key_enter
    with qtbot.waitSignal(tool.commit_requested, timeout=1000) as blocker:
        tool.key_enter(canvas.scene())
    assert blocker.args == [QRect(10, 10, 30, 30)]


def test_esc_clears_overlay(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.crop import CropTool
    stack = LayerStack(QSize(100, 80))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(100, 80)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = CropTool()
    canvas.set_tool(tool)
    tool.key_escape(canvas.scene())
    assert tool.is_committed_or_cancelled() is True
