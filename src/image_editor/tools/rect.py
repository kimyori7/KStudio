"""사각형 그리기 도구."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QUndoStack

from ..commands import AddAnnotationCommand
from ..items.rect import RectAnnotationItem
from ..scene import AnnotationScene
from .base import Tool

MIN_DRAG_PX = 5  # 이 미만 드래그는 자동 취소 (scene 좌표 기준)


class RectTool(Tool):
    name = "rect"

    def __init__(
        self,
        color: QColor,
        thickness_step: int,
        shift_held: Callable[[], bool],
        undo_stack: QUndoStack,
    ) -> None:
        self._color = QColor(color)
        self._thickness_step = int(thickness_step)
        self._shift_held = shift_held
        self._undo_stack = undo_stack
        self._draft: RectAnnotationItem | None = None
        self._origin: QPointF | None = None

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)

    def set_thickness_step(self, step: int) -> None:
        self._thickness_step = int(step)

    def mouse_press(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        self._origin = QPointF(scene_pos)
        self._draft = RectAnnotationItem(
            QRectF(scene_pos, scene_pos),
            self._color,
            self._thickness_step,
        )
        scene.add_annotation(self._draft)

    def mouse_move(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        if self._draft is None or self._origin is None:
            return
        rect = self._compute_rect(scene_pos)
        self._draft.set_rect(rect)

    def mouse_release(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        if self._draft is None:
            return
        rect = self._compute_rect(scene_pos)
        # 드래프트는 mouse_press 에서 직접 add 했으니 일단 제거 →
        # 너무 작으면 거기서 끝, 충분히 크면 AddAnnotationCommand 로 다시 추가 (Undo 가능)
        scene.remove_annotation(self._draft)
        draft = self._draft
        self._draft = None
        self._origin = None
        if rect.width() < MIN_DRAG_PX and rect.height() < MIN_DRAG_PX:
            return
        draft.set_rect(rect)
        self._undo_stack.push(AddAnnotationCommand(scene, draft))

    def key_escape(self, scene: AnnotationScene) -> None:
        if self._draft is not None:
            scene.remove_annotation(self._draft)
            self._draft = None
            self._origin = None

    def _compute_rect(self, current: QPointF) -> QRectF:
        assert self._origin is not None
        x1, y1 = self._origin.x(), self._origin.y()
        x2, y2 = current.x(), current.y()
        if self._shift_held():
            side = min(abs(x2 - x1), abs(y2 - y1))
            x2 = x1 + side * (1 if x2 >= x1 else -1)
            y2 = y1 + side * (1 if y2 >= y1 else -1)
        return QRectF(QPointF(min(x1, x2), min(y1, y2)),
                      QPointF(max(x1, x2), max(y1, y2)))
