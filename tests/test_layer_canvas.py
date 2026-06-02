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
    # AnnotationLayer 도 QGraphicsPixmapItem 으로 표시 (자체 scene 을 픽스맵으로 렌더).
    pixs = [i for i in canvas.scene().items() if isinstance(i, QGraphicsPixmapItem)]
    assert len(pixs) == 1


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


def test_set_tool_dispatches_mouse_press(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.base import Tool
    from PySide6.QtCore import QPointF

    class _ProbeTool(Tool):
        def __init__(self):
            self.pressed_at = None
            self.activated_called = False
            self.deactivated_called = False
        def activated(self, scene):
            self.activated_called = True
        def deactivated(self, scene):
            self.deactivated_called = True
        def mouse_press(self, scene, scene_pos):
            self.pressed_at = scene_pos

    stack = LayerStack(QSize(100, 100))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    canvas.show()
    tool = _ProbeTool()
    canvas.set_tool(tool)
    assert tool.activated_called is True
    qtbot.mouseClick(
        canvas.viewport(),
        Qt.LeftButton,
        pos=canvas.mapFromScene(QPointF(20, 20)),
    )
    assert tool.pressed_at is not None


def test_zoom_at_factor_scales_view(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.canvas import LayerCanvas
    stack = LayerStack(QSize(100, 100))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    canvas.show()
    canvas.set_zoom(2.0)
    assert abs(canvas.zoom_factor() - 2.0) < 0.001


def test_high_dpr_image_fills_canvas(qtbot):
    """HiDPI 스크린샷(DPR>1)을 캔버스 크기와 같은 device-pixel 로 로드하면
    그래픽스 아이템이 sceneRect 를 꽉 채워야 한다.

    DPR 정규화가 없으면 QGraphicsPixmapItem 이 1/DPR 로 축소돼 캔버스 우·하단에
    빈 체커가 드러나고(이미지가 캔버스를 못 채움), 삭제 영역도 어긋난다.
    """
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    pix = _solid(60, 40, 0xFFFF0000)
    pix.setDevicePixelRatio(1.5)
    stack = LayerStack(QSize(60, 40))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    stack.add_layer(ImageLayer(id=1, name="x", pixmap=pix))
    item = [i for i in canvas.scene().items() if isinstance(i, QGraphicsPixmapItem)][0]
    br = item.boundingRect()
    assert (round(br.width()), round(br.height())) == (60, 40)


def test_active_layer_signal_propagated(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.canvas import LayerCanvas
    from image_editor.layers.image_layer import ImageLayer
    from PySide6.QtGui import QImage
    stack = LayerStack(QSize(20, 20))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    pix = QImage(20, 20, QImage.Format_ARGB32)
    pix.fill(Qt.transparent)
    stack.add_layer(ImageLayer(id=1, name="x", pixmap=pix))
    stack.add_layer(ImageLayer(id=2, name="y", pixmap=pix))
    stack.set_active_layer(2)
    assert canvas.active_layer_id() == 2
