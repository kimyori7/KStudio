"""사각형 주석 아이템."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from ..thickness import thickness_to_pixels
from .base import AnnotationProperties


class RectAnnotationItem(QGraphicsItem):
    """테두리만 있는 사각형. 채움은 Phase 3+."""

    def __init__(
        self,
        rect: QRectF,
        color: QColor,
        thickness_step: int,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(parent)
        self._rect = QRectF(rect)
        self._props = AnnotationProperties(color, thickness_step)
        self._props.changed.connect(self._on_props_changed)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    # --- properties ---
    def rect(self) -> QRectF:
        return QRectF(self._rect)

    def set_rect(self, rect: QRectF) -> None:
        if self._rect == rect:
            return
        self.prepareGeometryChange()
        self._rect = QRectF(rect)
        self.update()

    def color(self) -> QColor:
        return self._props.color()

    def set_color(self, color: QColor) -> None:
        self._props.set_color(color)

    def thickness_step(self) -> int:
        return self._props.thickness_step()

    def set_thickness_step(self, step: int) -> None:
        self._props.set_thickness_step(step)

    # --- Qt overrides ---
    def boundingRect(self) -> QRectF:
        half = thickness_to_pixels(self._props.thickness_step()) / 2.0
        return self._rect.adjusted(-half, -half, half, half)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        px = thickness_to_pixels(self._props.thickness_step())
        pen = QPen(self._props.color(), px)
        pen.setJoinStyle(Qt.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self._rect)

    def _on_props_changed(self) -> None:
        self.prepareGeometryChange()
        self.update()
