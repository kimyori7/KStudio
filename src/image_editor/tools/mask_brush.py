"""MaskBrushTool — 활성 ImageLayer 의 마스크에 직접 칠하기.

mode='erase' 면 그린 영역의 마스크를 0(투명) 으로 만들고, mode='add' 면 255(불투명).
드래그 동안 layer.mask 에 직접 칠하고 stack.notify_layer_changed() 로 즉시 반영.
mouse_release 시 stroke_completed 시그널로 (prev_mask, new_mask) 를 보내 외부에서
QUndoCommand 로 감싸도록 한다.
"""
from __future__ import annotations
from typing import Callable, Optional

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsScene

from ..layer_model import LayerStack
from ..layers.image_layer import ImageLayer
from .base import Tool
from .raster_brush import make_cursor_ring


class _Emitter(QObject):
    stroke_completed = Signal(int, QImage, QImage)
    # (layer_id, prev_mask_or_null_image, new_mask)


class MaskBrushTool(Tool):
    name = "mask_brush"

    def __init__(
        self,
        stack: LayerStack,
        *,
        brush_size: int = 30,
        mode: str = "erase",   # "erase" 또는 "add"
    ) -> None:
        super().__init__()
        self._stack = stack
        self.brush_size = max(1, brush_size)
        self.mode = mode
        self._dragging = False
        self._layer_id: Optional[int] = None
        self._prev_mask: Optional[QImage] = None
        self._last_pt: Optional[QPointF] = None
        self._emitter = _Emitter()
        self.stroke_completed = self._emitter.stroke_completed
        self._cursor_ring: Optional[QGraphicsEllipseItem] = None
        self._scene: Optional[QGraphicsScene] = None

    # 사이즈 외부에서 갱신될 때 링도 동기화 (옵션바 슬라이더 → MainWindow → 이 setter)
    def set_size(self, size: int) -> None:
        self.brush_size = max(1, size)
        if self._cursor_ring is not None:
            half = self.brush_size / 2.0
            self._cursor_ring.setRect(-half, -half, self.brush_size, self.brush_size)

    def activated(self, scene: QGraphicsScene) -> None:
        self._scene = scene
        if self._cursor_ring is None:
            self._cursor_ring = make_cursor_ring(self.brush_size)
            scene.addItem(self._cursor_ring)

    def deactivated(self, scene: QGraphicsScene) -> None:
        if self._cursor_ring is not None and self._cursor_ring.scene() is scene:
            scene.removeItem(self._cursor_ring)
        self._cursor_ring = None
        self._scene = None

    # --- helpers ---
    def _active_image_layer(self) -> Optional[ImageLayer]:
        layer = self._stack.active_layer()
        return layer if isinstance(layer, ImageLayer) else None

    def _ensure_mask(self, layer: ImageLayer) -> QImage:
        """마스크가 없으면 흰색(=완전 불투명) 마스크를 만들어 부여."""
        if layer.mask is None or layer.mask.size() != layer.pixmap.size():
            m = QImage(layer.pixmap.size(), QImage.Format_Grayscale8)
            m.fill(255)
            layer.mask = m
        elif layer.mask.format() != QImage.Format_Grayscale8:
            layer.mask = layer.mask.convertToFormat(QImage.Format_Grayscale8)
        return layer.mask

    def _paint_stroke(self, layer: ImageLayer, p1: QPointF, p2: QPointF) -> None:
        mask = self._ensure_mask(layer)
        painter = QPainter(mask)
        painter.setRenderHint(QPainter.Antialiasing, True)
        gray = 0 if self.mode == "erase" else 255
        pen = QPen()
        pen.setWidth(self.brush_size)
        pen.setColor(Qt.black if gray == 0 else Qt.white)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        # layer-local 좌표로 변환 (scene 좌표 = canvas 좌표 = layer.offset 기준)
        local_p1 = p1 - QPointF(layer.offset)
        local_p2 = p2 - QPointF(layer.offset)
        painter.drawLine(local_p1, local_p2)
        painter.end()

    # --- Tool API ---
    def mouse_press(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        layer = self._active_image_layer()
        if layer is None:
            return
        self._dragging = True
        self._layer_id = layer.id
        # 시작 시점 마스크 스냅샷 (undo 용)
        self._prev_mask = layer.mask.copy() if layer.mask is not None else QImage()
        self._last_pt = QPointF(scene_pos)
        # 시작 점도 한 번 찍기
        self._paint_stroke(layer, scene_pos, scene_pos)
        self._stack.notify_pixmap_changed(self._layer_id)

    def mouse_move(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        # hover 든 drag 든 커서 링은 항상 따라가도록
        if self._cursor_ring is not None:
            self._cursor_ring.setPos(scene_pos)
        if not self._dragging or self._layer_id is None or self._last_pt is None:
            return
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer):
            return
        self._paint_stroke(layer, self._last_pt, scene_pos)
        self._last_pt = QPointF(scene_pos)
        self._stack.notify_pixmap_changed(self._layer_id)

    def mouse_release(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        if not self._dragging or self._layer_id is None:
            self._dragging = False
            return
        layer = self._stack.get_layer(self._layer_id)
        if isinstance(layer, ImageLayer):
            new_mask = layer.mask.copy() if layer.mask is not None else QImage()
            prev = self._prev_mask if self._prev_mask is not None else QImage()
            self._emitter.stroke_completed.emit(self._layer_id, prev, new_mask)
        self._dragging = False
        self._last_pt = None
        self._prev_mask = None
        self._layer_id = None
