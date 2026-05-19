"""마술봉 → SelectionModel → SelectionOverlay marching-ants 연동 검증.

MagicWandTool.preview_changed 가 발화되면 main_window 가 SelectionModel.set_rect 으로
변환하고, SelectionOverlay 가 자동으로 marching-ants 사각형 두 아이템(흰/검정)을 띄운다.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QImage


def _solid(w, h, c=0xFFFFFFFF):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor.fromRgba(c))
    return img


def test_magic_wand_preview_drives_marching_ants(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.selection import SelectionModel
    from image_editor.tools.magic_wand import MagicWandTool

    stack = LayerStack(QSize(30, 30))
    layer = ImageLayer(id=1, name="bg", pixmap=_solid(30, 30))
    stack.add_layer(layer)
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    model = SelectionModel()
    canvas.attach_selection(model)
    tool = MagicWandTool(stack, tolerance=10)
    canvas.set_tool(tool)
    # main_window 가 하는 일을 그대로 재현 — preview_changed → set_rect.
    def on_preview(lid, affected_local):
        layer_obj = stack.get_layer(lid)
        if affected_local is None or layer_obj is None:
            model.clear()
            return
        scene_rect = QRect(affected_local)
        scene_rect.translate(int(layer_obj.offset.x()), int(layer_obj.offset.y()))
        model.set_rect(scene_rect)
    tool.preview_changed.connect(on_preview)
    # 클릭 → 미리보기 + bounding rect 가 selection 에 들어가야 한다.
    tool.mouse_press(canvas.scene(), QPointF(10, 10))
    assert model.has_selection() is True
    # SelectionOverlay 가 scene 에 marching-ants 아이템 2개(흰/검정)를 만들었어야.
    # 마술봉 preview 픽스맵(z=900000)은 제외.
    items = [it for it in canvas.scene().items()
             if 99_999 <= it.zValue() <= 100_001]
    assert len(items) == 2


def test_magic_wand_cancel_clears_marching_ants(qtbot):
    """Esc → preview_changed(None) → selection.clear → overlay 아이템 제거."""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.selection import SelectionModel
    from image_editor.tools.magic_wand import MagicWandTool

    stack = LayerStack(QSize(30, 30))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(30, 30)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    model = SelectionModel()
    canvas.attach_selection(model)
    tool = MagicWandTool(stack, tolerance=10)
    canvas.set_tool(tool)

    def on_preview(lid, affected_local):
        layer_obj = stack.get_layer(lid)
        if affected_local is None or layer_obj is None:
            model.clear()
            return
        scene_rect = QRect(affected_local)
        scene_rect.translate(int(layer_obj.offset.x()), int(layer_obj.offset.y()))
        model.set_rect(scene_rect)
    tool.preview_changed.connect(on_preview)
    tool.mouse_press(canvas.scene(), QPointF(10, 10))
    assert model.has_selection()
    tool.key_escape(canvas.scene())
    assert model.has_selection() is False
    items = [it for it in canvas.scene().items()
             if 99_999 <= it.zValue() <= 100_001]
    assert items == []
