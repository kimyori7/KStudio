"""_on_auto_trim 계약 — rect 있으면 CropCommand push, None 이면 push 안 함."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter


def _img(w, h, bg, content_rect=None):
    im = QImage(w, h, QImage.Format_ARGB32)
    im.fill(QColor(bg))
    if content_rect:
        x, y, rw, rh = content_rect
        p = QPainter(im); p.fillRect(QRect(x, y, rw, rh), QColor("red")); p.end()
    return im


def test_compute_then_push_crops_stack(qtbot):
    """compute_trim_rect → CropCommand → undo_stack 흐름이 캔버스를 줄인다."""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.autotrim import compute_trim_rect
    from image_editor.operations.crop import CropCommand
    from PySide6.QtGui import QUndoStack
    im = _img(80, 40, "#1b1b1b", content_rect=(20, 10, 40, 20))
    stack = LayerStack(QSize(80, 40))
    stack.add_layer(ImageLayer(id=1, name="x", pixmap=im, offset=QPoint(0, 0)))
    undo = QUndoStack()
    rect = compute_trim_rect(im)
    assert rect is not None
    undo.push(CropCommand(stack, rect))
    assert stack.canvas_size == QSize(40, 20)
    undo.undo()
    assert stack.canvas_size == QSize(80, 40)


def test_uniform_image_yields_no_rect(qtbot):
    from image_editor.operations.autotrim import compute_trim_rect
    assert compute_trim_rect(_img(40, 40, "#1b1b1b")) is None
