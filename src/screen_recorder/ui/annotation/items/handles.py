"""선택 핸들 — 부모 주석 아이템의 자식으로 붙는 작은 정사각형."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem

HANDLE_SIZE = 8.0  # 씬 좌표 기준 정사각형 변 길이


class Handle(QGraphicsRectItem):
    """작은 정사각형 핸들. 드래그 시 on_drag 콜백으로 부모에게 새 위치 전달."""

    def __init__(
        self,
        center: QPointF,
        on_drag,  # Callable[[QPointF], None]
        cursor_shape: Qt.CursorShape,
        parent: QGraphicsItem,
    ) -> None:
        s = HANDLE_SIZE
        super().__init__(QRectF(-s / 2, -s / 2, s, s), parent)
        self.setPos(center)
        self.setBrush(QBrush(QColor(255, 255, 255)))
        self.setPen(QPen(QColor(0, 0, 0), 1))
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setCursor(cursor_shape)
        self.setData(0, "handle")
        self._on_drag = on_drag

    def mouseMoveEvent(self, event):
        new_scene_pos = self.mapToScene(event.pos())
        self._on_drag(new_scene_pos)

    def mousePressEvent(self, event):
        # 부모 아이템이 드래그로 이동하지 않도록 이벤트 흡수
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()
