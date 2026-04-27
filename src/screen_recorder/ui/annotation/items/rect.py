"""사각형 주석 아이템."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from ..thickness import thickness_to_pixels
from .base import AnnotationProperties
from .handles import Handle


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
        self._rect_on_drag_start: QRectF | None = None
        self._undo_push_callback = None  # scene 이 add_annotation 시 주입

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

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() is not None:
            from .base import clamp_position_to_scene
            clamped = clamp_position_to_scene(
                self.boundingRect(),
                value,
                self.scene().sceneRect(),
            )
            if clamped != value:
                return clamped
        if change == QGraphicsItem.ItemSelectedHasChanged:
            if value:
                self._create_handles()
            else:
                self._destroy_handles()
        return super().itemChange(change, value)

    def _create_handles(self) -> None:
        r = self._rect
        specs = [
            (r.topLeft(), Qt.SizeFDiagCursor, "tl"),
            (QPointF(r.center().x(), r.top()), Qt.SizeVerCursor, "tc"),
            (r.topRight(), Qt.SizeBDiagCursor, "tr"),
            (QPointF(r.right(), r.center().y()), Qt.SizeHorCursor, "rc"),
            (r.bottomRight(), Qt.SizeFDiagCursor, "br"),
            (QPointF(r.center().x(), r.bottom()), Qt.SizeVerCursor, "bc"),
            (r.bottomLeft(), Qt.SizeBDiagCursor, "bl"),
            (QPointF(r.left(), r.center().y()), Qt.SizeHorCursor, "lc"),
        ]
        self._handles: list[Handle] = []
        for center, cursor, tag in specs:
            h = Handle(
                center,
                lambda p, t=tag: self._on_handle_drag(t, p),
                cursor,
                parent=self,
                on_press=self._on_handle_press,
                on_release=self._on_handle_release,
            )
            self._handles.append(h)

    def _destroy_handles(self) -> None:
        for h in getattr(self, "_handles", []):
            if h.scene() is not None:
                h.scene().removeItem(h)
        self._handles = []

    def _on_handle_drag(self, tag: str, new_pos: QPointF) -> None:
        r = QRectF(self._rect)
        if "t" in tag:
            r.setTop(new_pos.y())
        if "b" in tag:
            r.setBottom(new_pos.y())
        if "l" in tag:
            r.setLeft(new_pos.x())
        if "r" in tag:
            r.setRight(new_pos.x())
        self.set_rect(r.normalized())
        self._reposition_handles()

    def _reposition_handles(self) -> None:
        if not getattr(self, "_handles", []):
            return
        r = self._rect
        positions = [
            r.topLeft(),
            QPointF(r.center().x(), r.top()),
            r.topRight(),
            QPointF(r.right(), r.center().y()),
            r.bottomRight(),
            QPointF(r.center().x(), r.bottom()),
            r.bottomLeft(),
            QPointF(r.left(), r.center().y()),
        ]
        for h, p in zip(self._handles, positions):
            h.setPos(p)

    def _on_handle_press(self) -> None:
        self._rect_on_drag_start = QRectF(self._rect)

    def _on_handle_release(self) -> None:
        if self._rect_on_drag_start is None:
            return
        old = self._rect_on_drag_start
        new = QRectF(self._rect)
        self._rect_on_drag_start = None
        if old == new:
            return
        cb = self._undo_push_callback
        if cb is not None:
            from ..commands import ChangeRectCommand
            # 현재 rect 를 old 로 되돌린 뒤 커맨드가 redo 로 new 적용 (stack 등록)
            self.set_rect(old)
            self._reposition_handles()
            cb(ChangeRectCommand(self, old, new))
