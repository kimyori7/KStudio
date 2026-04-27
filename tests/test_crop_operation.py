"""CropCommand — canvas_size 변경 + 모든 레이어 offset 갱신, undo 시 복원."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#ff0000"))
    return img


def test_crop_changes_canvas_size_and_offsets(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.crop import CropCommand
    stack = LayerStack(QSize(200, 100))
    layer = ImageLayer(id=1, name="x", pixmap=_solid(200, 100), offset=QPoint(0, 0))
    stack.add_layer(layer)
    cmd = CropCommand(stack, QRect(40, 20, 100, 60))
    cmd.redo()
    assert stack.canvas_size == QSize(100, 60)
    assert layer.offset == QPoint(-40, -20)


def test_crop_undo_restores(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.crop import CropCommand
    stack = LayerStack(QSize(200, 100))
    layer = ImageLayer(id=1, name="x", pixmap=_solid(200, 100))
    stack.add_layer(layer)
    cmd = CropCommand(stack, QRect(40, 20, 100, 60))
    cmd.redo()
    cmd.undo()
    assert stack.canvas_size == QSize(200, 100)
    assert layer.offset == QPoint(0, 0)
