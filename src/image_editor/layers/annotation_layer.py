"""AnnotationLayer — 벡터 주석 시스템을 단일 레이어로."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QGraphicsItem

from ..scene import AnnotationScene
from .base import Layer


class AnnotationLayer(Layer):
    """투명 배경 위에 벡터 아이템들이 올라가는 레이어.

    내부적으로 `AnnotationScene` 을 재활용하되, 배경 이미지는 투명 placeholder.
    캔버스 크기 변동 시 scene rect 도 함께 갱신.
    """

    def __init__(
        self, id: int, name: str, *,
        canvas_size: QSize,
        visible: bool = True,
        opacity: float = 1.0,
    ) -> None:
        super().__init__(id, name, visible=visible, opacity=opacity)
        # 투명 배경 — AnnotationScene 이 배경 이미지를 반드시 요구하므로 placeholder
        self._bg = QImage(canvas_size, QImage.Format_ARGB32)
        self._bg.fill(Qt.transparent)
        self._scene = AnnotationScene(self._bg)
        self._canvas_size = QSize(canvas_size)

    @property
    def scene(self) -> AnnotationScene:
        return self._scene

    def add_item(self, item: QGraphicsItem) -> None:
        self._scene.add_annotation(item)

    def remove_item(self, item: QGraphicsItem) -> None:
        self._scene.remove_annotation(item)

    def items(self) -> list[QGraphicsItem]:
        return self._scene.annotations()

    def render(self, canvas_size: QSize) -> QImage:
        out = QImage(canvas_size, QImage.Format_ARGB32)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        try:
            painter.setOpacity(self.opacity)
            self._scene.render(
                painter,
                QRectF(0, 0, canvas_size.width(), canvas_size.height()),
                self._scene.sceneRect(),
            )
        finally:
            painter.end()
        return out

    def apply_crop(self, rect: QRect) -> None:
        # scene 좌표를 평행이동: 모든 아이템 위치를 -rect.topLeft 만큼 옮기고 sceneRect 갱신
        dx, dy = -rect.x(), -rect.y()
        for it in self.items():
            it.setPos(QPointF(it.pos().x() + dx, it.pos().y() + dy))
        self._canvas_size = QSize(rect.width(), rect.height())
        self._scene.setSceneRect(0, 0, rect.width(), rect.height())
