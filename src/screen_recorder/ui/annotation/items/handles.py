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
        on_press=None,   # Callable[[], None] | None
        on_release=None, # Callable[[], None] | None
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
        self._on_press = on_press
        self._on_release = on_release

    def mouseMoveEvent(self, event):
        new_scene_pos = self.mapToScene(event.pos())
        self._on_drag(new_scene_pos)

    def mousePressEvent(self, event):
        if self._on_press:
            self._on_press()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._on_release:
            self._on_release()
        event.accept()
