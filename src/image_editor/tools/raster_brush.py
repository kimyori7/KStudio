"""RasterBrushTool — 활성 ImageLayer 의 픽셀 자체를 칠하기 (paint) 또는 지우기 (erase).

mode='paint': 현재 색으로 두께 size 의 둥근 스트로크를 layer.pixmap 에 그린다.
mode='erase': layer.pixmap 의 alpha 를 0 으로 만든다 (투명).

마우스 hover 시 커서 위치에 size 크기의 동그라미 미리보기 링을 scene 에 표시.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsScene

from ..layer_model import LayerStack
from ..layers.image_layer import ImageLayer
from .base import Tool


class _Emitter(QObject):
    stroke_completed = Signal(int, QImage, QImage)
    # (layer_id, prev_pixmap, new_pixmap)


def make_cursor_ring(size: int) -> QGraphicsEllipseItem:
    """브러시 크기 미리보기 링 — scene 에 추가해 mouse hover 마다 위치 갱신."""
    item = QGraphicsEllipseItem()
    pen = QPen(QColor(0, 0, 0, 220))
    pen.setWidthF(1.0)
    pen.setCosmetic(True)
    item.setPen(pen)
    item.setBrush(Qt.NoBrush)
    item.setZValue(1_000_000)
    half = size / 2.0
    item.setRect(-half, -half, size, size)
    item.setAcceptedMouseButtons(Qt.NoButton)   # 클릭 통과
    return item


class RasterBrushTool(Tool):
    name = "raster_brush"

    def __init__(
        self,
        stack: LayerStack,
        *,
        color: QColor = QColor(0, 0, 0),
        size: int = 20,
        mode: str = "paint",   # "paint" 또는 "erase"
    ) -> None:
        super().__init__()
        self._stack = stack
        self.color = QColor(color)
        self.size = max(1, size)
        self.mode = mode
        self._dragging = False
        self._layer_id: Optional[int] = None
        self._prev_pixmap: Optional[QImage] = None
        self._last_pt: Optional[QPointF] = None
        self._scene: Optional[QGraphicsScene] = None
        self._cursor_ring: Optional[QGraphicsEllipseItem] = None
        self._emitter = _Emitter()
        self.stroke_completed = self._emitter.stroke_completed

    # ----- size/mode 변경 시 링 갱신 -----
    def set_size(self, size: int) -> None:
        self.size = max(1, size)
        if self._cursor_ring is not None:
            half = self.size / 2.0
            self._cursor_ring.setRect(-half, -half, self.size, self.size)

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def set_color(self, color: QColor) -> None:
        self.color = QColor(color)

    # ----- Tool API -----
    def activated(self, scene: QGraphicsScene) -> None:
        self._scene = scene
        if self._cursor_ring is None:
            self._cursor_ring = make_cursor_ring(self.size)
            scene.addItem(self._cursor_ring)

    def deactivated(self, scene: QGraphicsScene) -> None:
        if self._cursor_ring is not None and self._cursor_ring.scene() is scene:
            scene.removeItem(self._cursor_ring)
        self._cursor_ring = None
        self._dragging = False
        self._scene = None

    def _active_image_layer(self) -> Optional[ImageLayer]:
        layer = self._stack.active_layer()
        return layer if isinstance(layer, ImageLayer) else None

    def _paint_segment(self, layer: ImageLayer, p1: QPointF, p2: QPointF) -> None:
        # layer-local 좌표
        offs = layer.offset
        local_p1 = p1 - QPointF(offs)
        local_p2 = p2 - QPointF(offs)
        painter = QPainter(layer.pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self.mode == "erase":
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            pen_color = QColor(0, 0, 0, 0)
        else:
            pen_color = QColor(self.color)
        pen = QPen(pen_color)
        pen.setWidth(self.size)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(local_p1, local_p2)
        painter.end()

    def mouse_press(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        layer = self._active_image_layer()
        if layer is None:
            return
        self._dragging = True
        self._layer_id = layer.id
        self._prev_pixmap = layer.pixmap.copy()
        self._last_pt = QPointF(scene_pos)
        self._paint_segment(layer, scene_pos, scene_pos)
        self._stack.notify_pixmap_changed(layer.id)

    def mouse_move(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        # hover 든 drag 든 커서 링은 항상 따라가도록
        if self._cursor_ring is not None:
            self._cursor_ring.setPos(scene_pos)
        if not self._dragging or self._layer_id is None or self._last_pt is None:
            return
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer):
            return
        self._paint_segment(layer, self._last_pt, scene_pos)
        self._last_pt = QPointF(scene_pos)
        self._stack.notify_pixmap_changed(layer.id)

    def mouse_release(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        if not self._dragging or self._layer_id is None:
            self._dragging = False
            return
        layer = self._stack.get_layer(self._layer_id)
        if isinstance(layer, ImageLayer):
            new_pix = layer.pixmap.copy()
            prev = self._prev_pixmap if self._prev_pixmap is not None else QImage()
            self._emitter.stroke_completed.emit(self._layer_id, prev, new_pix)
        self._dragging = False
        self._last_pt = None
        self._prev_pixmap = None
        self._layer_id = None
