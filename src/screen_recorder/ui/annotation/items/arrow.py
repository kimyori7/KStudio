"""화살표 주석 아이템 — 선 + 끝점 삼각형 머리."""
from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from ..thickness import thickness_to_pixels
from .base import AnnotationProperties
from .handles import Handle


class ArrowAnnotationItem(QGraphicsItem):
    """시작점 → 끝점으로 뻗는 직선 + 끝점에 삼각형 머리."""

    HEAD_LENGTH_MULT = 4.0  # 머리 길이 = 선 두께 × 4
    HEAD_WIDTH_MULT = 2.5   # 머리 폭 절반 = 선 두께 × 2.5

    def __init__(
        self,
        start: QPointF,
        end: QPointF,
        color: QColor,
        thickness_step: int,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(parent)
        self._start = QPointF(start)
        self._end = QPointF(end)
        self._props = AnnotationProperties(color, thickness_step)
        self._props.changed.connect(self._on_props_changed)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self._start_on_drag_start: QPointF | None = None
        self._end_on_drag_start: QPointF | None = None
        self._undo_push_callback = None

    # --- endpoints ---
    def start(self) -> QPointF:
        return QPointF(self._start)

    def end(self) -> QPointF:
        return QPointF(self._end)

    def set_start(self, p: QPointF) -> None:
        if self._start != p:
            self.prepareGeometryChange()
            self._start = QPointF(p)
            self.update()

    def set_end(self, p: QPointF) -> None:
        if self._end != p:
            self.prepareGeometryChange()
            self._end = QPointF(p)
            self.update()

    # --- properties delegate ---
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
        px = thickness_to_pixels(self._props.thickness_step())
        padding = max(px, px * self.HEAD_LENGTH_MULT) + 1
        line_rect = QRectF(self._start, self._end).normalized()
        return line_rect.adjusted(-padding, -padding, padding, padding)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        px = thickness_to_pixels(self._props.thickness_step())
        color = self._props.color()
        pen = QPen(color, px)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.setBrush(color)

        # 선은 머리 시작점까지만 그림 (겹침 방지)
        line = QLineF(self._start, self._end)
        length = line.length()
        if length < 1e-6:
            return
        head_len = px * self.HEAD_LENGTH_MULT
        shaft_end_t = max(0.0, (length - head_len) / length)
        shaft_end = QPointF(
            self._start.x() + (self._end.x() - self._start.x()) * shaft_end_t,
            self._start.y() + (self._end.y() - self._start.y()) * shaft_end_t,
        )
        painter.drawLine(self._start, shaft_end)

        # 머리 삼각형
        angle = math.atan2(self._end.y() - self._start.y(), self._end.x() - self._start.x())
        head_w = px * self.HEAD_WIDTH_MULT
        left = QPointF(
            shaft_end.x() + math.sin(angle) * head_w,
            shaft_end.y() - math.cos(angle) * head_w,
        )
        right = QPointF(
            shaft_end.x() - math.sin(angle) * head_w,
            shaft_end.y() + math.cos(angle) * head_w,
        )
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPolygonF([self._end, left, right]))

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
        self._handles: list[Handle] = []
        start_h = Handle(
            self._start,
            lambda p: self._on_handle_drag("start", p),
            Qt.CrossCursor,
            parent=self,
            on_press=self._on_handle_press,
            on_release=self._on_handle_release,
        )
        end_h = Handle(
            self._end,
            lambda p: self._on_handle_drag("end", p),
            Qt.CrossCursor,
            parent=self,
            on_press=self._on_handle_press,
            on_release=self._on_handle_release,
        )
        self._handles.extend([start_h, end_h])

    def _destroy_handles(self) -> None:
        for h in getattr(self, "_handles", []):
            if h.scene() is not None:
                h.scene().removeItem(h)
        self._handles = []

    def _on_handle_drag(self, which: str, new_pos: QPointF) -> None:
        if which == "start":
            self.set_start(new_pos)
        else:
            self.set_end(new_pos)
        self._reposition_handles()

    def _reposition_handles(self) -> None:
        hs = getattr(self, "_handles", [])
        if len(hs) == 2:
            hs[0].setPos(self._start)
            hs[1].setPos(self._end)

    def _on_handle_press(self) -> None:
        self._start_on_drag_start = QPointF(self._start)
        self._end_on_drag_start = QPointF(self._end)

    def _on_handle_release(self) -> None:
        if self._start_on_drag_start is None or self._end_on_drag_start is None:
            return
        os_, oe_ = self._start_on_drag_start, self._end_on_drag_start
        ns_, ne_ = QPointF(self._start), QPointF(self._end)
        self._start_on_drag_start = None
        self._end_on_drag_start = None
        if os_ == ns_ and oe_ == ne_:
            return
        cb = self._undo_push_callback
        if cb is not None:
            from ..commands import ChangeArrowEndpointsCommand
            self.set_start(os_)
            self.set_end(oe_)
            self._reposition_handles()
            cb(ChangeArrowEndpointsCommand(self, os_, oe_, ns_, ne_))
