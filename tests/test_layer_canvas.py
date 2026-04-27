"""LayerCanvas — LayerStack 시그널을 시각화에 반영."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsItemGroup


def _solid(w: int, h: int, c: int) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor.fromRgba(c))
    return img


def test_canvas_creates_scene_with_canvas_rect(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.canvas import LayerCanvas
    stack = LayerStack(QSize(120, 80))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    assert canvas.scene().sceneRect().width() == 120
    assert canvas.scene().sceneRect().height() == 80


def test_add_image_layer_creates_pixmap_item(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    stack = LayerStack(QSize(50, 50))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    layer = ImageLayer(id=1, name="bg", pixmap=_solid(50, 50, 0xFFFF0000))
    stack.add_layer(layer)
    items = [i for i in canvas.scene().items() if isinstance(i, QGraphicsPixmapItem)]
    assert len(items) == 1


def test_add_annotation_layer_creates_group(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.annotation_layer import AnnotationLayer
    from image_editor.canvas import LayerCanvas
    stack = LayerStack(QSize(50, 50))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    layer = AnnotationLayer(id=2, name="annot", canvas_size=QSize(50, 50))
    stack.add_layer(layer)
    groups = [i for i in canvas.scene().items() if isinstance(i, QGraphicsItemGroup)]
    assert len(groups) == 1


def test_remove_layer_removes_item(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    stack = LayerStack(QSize(50, 50))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    stack.add_layer(ImageLayer(id=1, name="x", pixmap=_solid(50, 50, 0xFF00FF00)))
    stack.remove_layer(1)
    pixs = [i for i in canvas.scene().items() if isinstance(i, QGraphicsPixmapItem)]
    assert len(pixs) == 0


def test_visibility_toggle_hides_item(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    stack = LayerStack(QSize(50, 50))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    layer = ImageLayer(id=1, name="x", pixmap=_solid(50, 50, 0xFFFFFFFF))
    stack.add_layer(layer)
    layer.visible = False
    stack.notify_layer_changed()
    items = [i for i in canvas.scene().items() if isinstance(i, QGraphicsPixmapItem)]
    assert items[0].isVisible() is False


def test_canvas_size_change_updates_scene_rect(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.canvas import LayerCanvas
    stack = LayerStack(QSize(100, 100))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    stack.set_canvas_size(QSize(200, 150))
    assert canvas.scene().sceneRect().width() == 200
    assert canvas.scene().sceneRect().height() == 150


def test_composite_returns_combined_image(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    stack = LayerStack(QSize(20, 20))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    stack.add_layer(ImageLayer(id=1, name="x", pixmap=_solid(20, 20, 0xFF00FF00)))
    out = canvas.composite()
    assert out.size() == QSize(20, 20)
    assert QColor(out.pixel(10, 10)).green() == 255
