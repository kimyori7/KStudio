"""BackgroundRemovalCommand — rembg 호출(주입 가능)·마스크 적용·undo."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w, h, c=0xFFFFFFFF):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor.fromRgba(c))
    return img


def _fake_remove_bg(img: QImage) -> QImage:
    """모든 픽셀을 투명으로 바꾸는 fake 마스크 (테스트용)."""
    m = QImage(img.size(), QImage.Format_Grayscale8)
    m.fill(0)
    return m


def test_apply_sets_mask_and_undo_clears(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.background_removal import BackgroundRemovalCommand
    stack = LayerStack(QSize(20, 20))
    layer = ImageLayer(id=1, name="bg", pixmap=_solid(20, 20))
    stack.add_layer(layer)
    cmd = BackgroundRemovalCommand(stack, layer_id=1, remove_bg_fn=_fake_remove_bg)
    cmd.run_sync()
    cmd.redo()
    assert layer.mask is not None
    cmd.undo()
    assert layer.mask is None


def test_apply_preserves_original_pixmap(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.background_removal import BackgroundRemovalCommand
    stack = LayerStack(QSize(20, 20))
    pix = _solid(20, 20, 0xFFFF0000)
    layer = ImageLayer(id=1, name="bg", pixmap=pix)
    stack.add_layer(layer)
    cmd = BackgroundRemovalCommand(stack, layer_id=1, remove_bg_fn=_fake_remove_bg)
    cmd.run_sync()
    cmd.redo()
    assert QColor(layer.pixmap.pixel(5, 5)).red() == 255  # 원본 픽셀 보존


def test_run_async_emits_finished(qtbot):
    """기본 비동기 모드 — finished 시그널 발행."""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.background_removal import BackgroundRemovalCommand
    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(20, 20)))
    cmd = BackgroundRemovalCommand(stack, layer_id=1, remove_bg_fn=_fake_remove_bg)
    with qtbot.waitSignal(cmd.finished, timeout=2000):
        cmd.run_async()
