"""화살표 그리기 도구."""
from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor

from ..items.arrow import ArrowAnnotationItem
from ..scene import AnnotationScene
from .base import Tool
from .rect import MIN_DRAG_PX


class ArrowTool(Tool):
    name = "arrow"

    def __init__(
        self,
        color: QColor,
        thickness_step: int,
        shift_held: Callable[[], bool],
    ) -> None:
        self._color = QColor(color)
        self._thickness_step = int(thickness_step)
        self._shift_held = shift_held
        self._draft: ArrowAnnotationItem | None = None
        self._origin: QPointF | None = None

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)

    def set_thickness_step(self, step: int) -> None:
        self._thickness_step = int(step)

    def mouse_press(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        self._origin = QPointF(scene_pos)
        self._draft = ArrowAnnotationItem(
            scene_pos, scene_pos, self._color, self._thickness_step
        )
        scene.add_annotation(self._draft)

    def mouse_move(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        if self._draft is None or self._origin is None:
            return
        end = self._compute_end(scene_pos)
        self._draft.set_end(end)

    def mouse_release(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        if self._draft is None or self._origin is None:
            return
        end = self._compute_end(scene_pos)
        dx = abs(end.x() - self._origin.x())
        dy = abs(end.y() - self._origin.y())
        if dx < MIN_DRAG_PX and dy < MIN_DRAG_PX:
            scene.remove_annotation(self._draft)
        else:
            self._draft.set_end(end)
        self._draft = None
        self._origin = None

    def key_escape(self, scene: AnnotationScene) -> None:
        if self._draft is not None:
            scene.remove_annotation(self._draft)
            self._draft = None
            self._origin = None

    def _compute_end(self, current: QPointF) -> QPointF:
        assert self._origin is not None
        if not self._shift_held():
            return QPointF(current)
        dx = current.x() - self._origin.x()
        dy = current.y() - self._origin.y()
        angle = math.atan2(dy, dx)
        # 45도 스냅
        snap = round(angle / (math.pi / 4)) * (math.pi / 4)
        length = math.hypot(dx, dy)
        return QPointF(
            self._origin.x() + math.cos(snap) * length,
            self._origin.y() + math.sin(snap) * length,
        )
