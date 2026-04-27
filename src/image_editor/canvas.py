"""LayerCanvas — LayerStack 을 QGraphicsScene 으로 시각화."""
from __future__ import annotations
from typing import Dict

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsItemGroup, QGraphicsPixmapItem,
    QGraphicsScene, QGraphicsView,
)

from .layer_model import LayerStack
from .layers.annotation_layer import AnnotationLayer
from .layers.base import Layer
from .layers.image_layer import ImageLayer


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
