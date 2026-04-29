"""RasterBrushTool — 활성 ImageLayer 의 픽셀 자체를 칠하기 (paint) 또는 지우기 (erase).

mode='paint': 현재 색으로 두께 size 의 둥근 스트로크를 layer.pixmap 에 그린다.
mode='erase': layer.pixmap 의 alpha 를 0 으로 만든다 (투명).

마우스 hover 시 커서 위치에 size 크기의 동그라미 미리보기 링을 scene 에 표시.
링 색상은 커서 아래 픽셀의 밝기에 따라 흑/백을 자동 선택해 어떤 배경에서도 잘 보이도록 한다.
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
    """브러시 크기 미리보기 링 — scene 에 추가해 mouse hover 마다 위치 갱신.

    링은 두 겹(검은 안쪽/흰 바깥쪽 또는 그 반대)으로 그리지 않고, set_ring_color 가
    동적으로 한 가지 색을 골라 적용한다. 어떤 배경에서도 보이게 하는 핵심은 밝기 대비.
    """
    item = QGraphicsEllipseItem()
    pen = QPen(QColor(0, 0, 0, 220))
    pen.setWidthF(2.0)
    pen.setCosmetic(True)
    item.setPen(pen)
    item.setBrush(Qt.NoBrush)
    item.setZValue(1_000_000)
    half = size / 2.0
    item.setRect(-half, -half, size, size)
    item.setAcceptedMouseButtons(Qt.NoButton)   # 클릭 통과
    return item


def _luma(color: int) -> int:
    """ARGB 정수에서 단순 luma 계산 (0~255). 알파는 무시 — 보이는 색 기준."""
    r = (color >> 16) & 0xFF
    g = (color >> 8) & 0xFF
    b = color & 0xFF
    # 빠른 근사 BT.601: 0.299R + 0.587G + 0.114B
    return (299 * r + 587 * g + 114 * b) // 1000


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
            self._update_ring_contrast(scene_pos)
        if not self._dragging or self._layer_id is None or self._last_pt is None:
            return
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer):
            return
        self._paint_segment(layer, self._last_pt, scene_pos)
        self._last_pt = QPointF(scene_pos)
        self._stack.notify_pixmap_changed(layer.id)

    def _update_ring_contrast(self, scene_pos: QPointF) -> None:
        """커서 아래 합성 픽셀을 보고 링 색을 흑/백 중 대비가 큰 쪽으로 즉시 전환.

        합성 결과는 모든 visible layer 를 (z 순서대로) 평탄화한 색 — `_sample_composite_argb`
        가 책임. 어두우면 흰 링, 밝으면 검은 링.
        """
        if self._cursor_ring is None:
            return
        argb = self._sample_composite_argb(scene_pos)
        if argb is None:
            return
        if _luma(argb) < 128:
            ring = QColor(255, 255, 255, 230)
        else:
            ring = QColor(0, 0, 0, 230)
        pen = self._cursor_ring.pen()
        if pen.color() == ring:
            return
        pen.setColor(ring)
        self._cursor_ring.setPen(pen)

    def _sample_composite_argb(self, scene_pos: QPointF) -> Optional[int]:
        """scene 좌표의 픽셀을 모든 visible 레이어를 위→아래로 합성해 ARGB 정수로 반환.

        가장 위 alpha=255 픽셀이 발견되면 즉시 종료. 알파가 부분이면 자체 색으로
        근사 (정확한 alpha-over 는 비용 대비 효과가 적어 생략). scene 영역 밖이면 None.
        """
        x = int(scene_pos.x())
        y = int(scene_pos.y())
        # canvas size 안인지 검사 — sceneRect 대신 stack.canvas_size 신뢰.
        cs = self._stack.canvas_size
        if x < 0 or y < 0 or x >= cs.width() or y >= cs.height():
            return None
        # 위 → 아래로 보면서 첫 번째 불투명 픽셀을 찾는다.
        for layer in reversed(self._stack.layers):
            if not layer.visible:
                continue
            if isinstance(layer, ImageLayer):
                lx = x - layer.offset.x()
                ly = y - layer.offset.y()
                pm = layer.pixmap
                if 0 <= lx < pm.width() and 0 <= ly < pm.height():
                    px = pm.pixel(lx, ly)
                    a = (px >> 24) & 0xFF
                    if a >= 16:
                        return px
        # 모든 레이어가 투명/없음 → 대비 결정 불가, 검은 링이 기본 (밝은 캔버스 가정)
        return 0xFFFFFFFF

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
