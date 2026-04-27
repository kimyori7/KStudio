"""텍스트 도구 — 클릭 위치에 빈 텍스트 박스 생성 + 편집 모드."""
from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QUndoStack

from ..commands import AddAnnotationCommand
from ..items.text import TextAnnotationItem
from ..scene import AnnotationScene
from .base import Tool


class TextTool(Tool):
    name = "text"

    def __init__(self, color: QColor, undo_stack: QUndoStack) -> None:
        self._color = QColor(color)
        self._undo_stack = undo_stack
        self._active: TextAnnotationItem | None = None

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)

    def mouse_press(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        # 다른 텍스트를 편집 중이었다면 먼저 확정
        self.commit_active(scene)
        t = TextAnnotationItem(scene_pos, "", self._color)
        scene.add_annotation(t)
        t.enter_edit_mode()
        self._active = t

    def mouse_release(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        pass

    def commit_active(self, scene: AnnotationScene) -> None:
        if self._active is None:
            return
        active = self._active
        self._active = None
        active.exit_edit_mode()
        if active.text().strip() == "":
            scene.remove_annotation(active)
            return
        # 텍스트는 mouse_press 시 이미 scene 에 추가됨 — 일단 제거 후 AddAnnotationCommand 로 재추가 (Undo 가능)
        scene.remove_annotation(active)
        self._undo_stack.push(AddAnnotationCommand(scene, active))

    def deactivated(self, scene: AnnotationScene) -> None:
        self.commit_active(scene)

    def double_click(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        for it in scene.items(scene_pos):
            if isinstance(it, TextAnnotationItem):
                it.enter_edit_mode()
                self._active = it
                return
