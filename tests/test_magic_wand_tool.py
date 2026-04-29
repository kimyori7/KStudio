"""MagicWandTool — 클릭으로 미리보기, Enter/Delete 로 확정하는 두 단계 동작."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w, h, c=0xFFFFFFFF):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor.fromRgba(c))
    return img


def test_click_creates_pending_preview_without_modifying_mask(qtbot):
    """클릭만 하면 마스크는 그대로 — 미리보기 상태로만 들어가야 한다."""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.magic_wand import MagicWandTool

    stack = LayerStack(QSize(20, 20))
    layer = ImageLayer(id=1, name="bg", pixmap=_solid(20, 20))
    stack.add_layer(layer)
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)

    tool = MagicWandTool(stack, tolerance=10)
    canvas.set_tool(tool)
    assert layer.mask is None
    tool.mouse_press(canvas.scene(), QPointF(5, 5))
    # 마스크는 아직 바뀌면 안 된다.
    assert layer.mask is None
    # 그러나 보류 상태로 들어가 있어야 한다.
    assert tool.has_pending() is True


def test_enter_commits_pending_preview(qtbot):
    """Enter 누르면 commit_requested 시그널이 발화되고 보류가 해제된다."""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.magic_wand import MagicWandTool

    stack = LayerStack(QSize(20, 20))
    layer = ImageLayer(id=1, name="bg", pixmap=_solid(20, 20))
    stack.add_layer(layer)
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = MagicWandTool(stack, tolerance=10)
    canvas.set_tool(tool)
    tool.mouse_press(canvas.scene(), QPointF(5, 5))
    assert tool.has_pending()
    with qtbot.waitSignal(tool.commit_requested, timeout=500) as blocker:
        tool.key_enter(canvas.scene())
    layer_id, mask, affected = blocker.args
    assert layer_id == 1
    assert isinstance(mask, QImage)
    assert affected is not None
    assert tool.has_pending() is False


def test_delete_also_commits_pending(qtbot):
    """Delete 키도 보류 미리보기를 확정해야 한다 (사용자 직관)."""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.magic_wand import MagicWandTool

    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(20, 20)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = MagicWandTool(stack, tolerance=10)
    canvas.set_tool(tool)
    tool.mouse_press(canvas.scene(), QPointF(5, 5))
    # 보류 상태에서 Delete 키 → consumed=True 반환.
    consumed = tool.key_delete(canvas.scene())
    assert consumed is True
    assert tool.has_pending() is False


def test_escape_clears_pending_without_commit(qtbot):
    """Esc 는 보류 미리보기만 폐기 — commit 시그널은 발화되지 않는다."""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.magic_wand import MagicWandTool

    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(20, 20)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = MagicWandTool(stack, tolerance=10)
    canvas.set_tool(tool)
    tool.mouse_press(canvas.scene(), QPointF(5, 5))
    assert tool.has_pending()
    with qtbot.assertNotEmitted(tool.commit_requested):
        with qtbot.waitSignal(tool.cancelled, timeout=500):
            tool.key_escape(canvas.scene())
    assert tool.has_pending() is False
