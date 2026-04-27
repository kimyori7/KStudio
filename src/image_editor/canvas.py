"""LayerCanvas — LayerStack 을 QGraphicsScene 으로 시각화."""
from __future__ import annotations
from typing import Dict, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsItemGroup, QGraphicsPixmapItem,
    QGraphicsScene, QGraphicsView,
)

from .layer_model import LayerStack
from .layers.annotation_layer import AnnotationLayer
from .layers.base import Layer
from .layers.image_layer import ImageLayer
from .tools.base import Tool

ZOOM_MIN = 0.25
ZOOM_MAX = 4.0
ZOOM_STEP = 1.15


class LayerCanvas(QGraphicsView):
    def __init__(self, stack: LayerStack) -> None:
        self._stack = stack
        self._scene = QGraphicsScene()
        super().__init__(self._scene)
        self._items: Dict[int, QGraphicsItem] = {}   # layer_id → scene item
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._sync_scene_rect()
        self._stack.layers_changed.connect(self._rebuild_items)
        self._stack.canvas_size_changed.connect(self._sync_scene_rect)
        self._tool: Optional[Tool] = None
        self._zoom: float = 1.0
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setFocusPolicy(Qt.StrongFocus)
        self._stack.active_layer_changed.connect(self._on_active_changed)
        self._rebuild_items()

    # --- 모델 → 뷰 ---
    def _sync_scene_rect(self) -> None:
        s = self._stack.canvas_size
        self._scene.setSceneRect(QRectF(0, 0, s.width(), s.height()))

    def _rebuild_items(self) -> None:
        # 단순 전략: 매번 전체 동기화 (성능 충분, 1차 단순성 우선)
        existing_ids = set(self._items.keys())
        wanted_ids = {l.id for l in self._stack.layers}
        # 제거
        for lid in existing_ids - wanted_ids:
            it = self._items.pop(lid)
            self._scene.removeItem(it)
        # 추가/갱신
        for z, layer in enumerate(self._stack.layers):
            it = self._items.get(layer.id)
            if it is None:
                it = self._make_item(layer)
                self._items[layer.id] = it
                self._scene.addItem(it)
            self._update_item(it, layer, z)

    def _make_item(self, layer: Layer) -> QGraphicsItem:
        if isinstance(layer, ImageLayer):
            return QGraphicsPixmapItem()
        if isinstance(layer, AnnotationLayer):
            return QGraphicsItemGroup()
        # 알 수 없는 타입은 placeholder
        return QGraphicsItemGroup()

    def _update_item(self, it: QGraphicsItem, layer: Layer, z: int) -> None:
        it.setVisible(bool(layer.visible))
        it.setOpacity(float(layer.opacity))
        it.setZValue(z)
        if isinstance(layer, ImageLayer) and isinstance(it, QGraphicsPixmapItem):
            pix = QPixmap.fromImage(layer.composed_pixmap())
            it.setPixmap(pix)
            it.setPos(layer.offset)
        elif isinstance(layer, AnnotationLayer) and isinstance(it, QGraphicsItemGroup):
            # AnnotationLayer 는 자체 scene 을 갖고 있어 직접 그려넣기는 어려움.
            # 1차 전략: AnnotationLayer 의 아이템들을 group 의 자식으로 직접 추가/동기화.
            current_children = set(it.childItems())
            wanted = set(layer.items())
            for child in current_children - wanted:
                it.removeFromGroup(child)
            for child in wanted - current_children:
                # child 가 AnnotationLayer 의 scene 에 속한 상태에선 중복 추가 안 됨.
                # 1차 단순화: 아이템을 layer.scene 에서 떼어 group 에 붙임.
                if child.scene() is layer.scene:
                    layer.scene.removeItem(child)
                it.addToGroup(child)

    # --- 합성 출력 ---
    def composite(self) -> QImage:
        out = QImage(self._stack.canvas_size, QImage.Format_ARGB32)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        try:
            for layer in self._stack.layers:
                if not layer.visible:
                    continue
                rendered = layer.render(self._stack.canvas_size)
                painter.setOpacity(1.0)
                painter.drawImage(0, 0, rendered)
        finally:
            painter.end()
        return out

    # --- 도구 ---
    def set_tool(self, tool: Optional[Tool]) -> None:
        if self._tool is tool:
            return
        if self._tool is not None:
            self._tool.deactivated(self._scene)
        self._tool = tool
        if tool is not None:
            tool.activated(self._scene)

    def current_tool(self) -> Optional[Tool]:
        return self._tool

    def active_layer_id(self) -> Optional[int]:
        return self._stack.active_layer_id

    def _on_active_changed(self, lid: int) -> None:
        # 후속에 도구 활/비활 정책에 사용. 현재는 이벤트 후크 자리만.
        pass

    # --- 줌 ---
    def zoom_factor(self) -> float:
        return self._zoom

    def set_zoom(self, factor: float) -> None:
        factor = max(ZOOM_MIN, min(ZOOM_MAX, factor))
        if abs(factor - self._zoom) < 1e-6:
            return
        ratio = factor / self._zoom
        self._zoom = factor
        self.scale(ratio, ratio)

    def zoom_in_at_cursor(self) -> None:
        self.set_zoom(self._zoom * ZOOM_STEP)

    def zoom_out_at_cursor(self) -> None:
        self.set_zoom(self._zoom / ZOOM_STEP)

    def fit_to_view(self) -> None:
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        # fitInView 가 transform 을 직접 바꾸므로 _zoom 동기화
        self._zoom = self.transform().m11()

    # --- 이벤트 ---
    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in_at_cursor()
            else:
                self.zoom_out_at_cursor()
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._tool is not None:
            scene_pos = self.mapToScene(e.position().toPoint())
            self._tool.mouse_press(self._scene, scene_pos)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._tool is not None:
            scene_pos = self.mapToScene(e.position().toPoint())
            self._tool.mouse_move(self._scene, scene_pos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._tool is not None:
            scene_pos = self.mapToScene(e.position().toPoint())
            self._tool.mouse_release(self._scene, scene_pos)
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        if self._tool is not None:
            scene_pos = self.mapToScene(e.position().toPoint())
            self._tool.double_click(self._scene, scene_pos)
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if self._tool is not None:
            if e.key() == Qt.Key_Escape:
                self._tool.key_escape(self._scene)
            elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._tool.key_enter(self._scene)
        super().keyPressEvent(e)
