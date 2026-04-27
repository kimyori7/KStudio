"""텍스트 도구 — 클릭 위치에 빈 텍스트 박스 생성 + 편집 모드."""
from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor

from ..items.text import TextAnnotationItem
from ..scene import AnnotationScene
from .base import Tool


class TextTool(Tool):
    name = "text"

    def __init__(self, color: QColor) -> None:
        self._color = QColor(color)
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
        pass  # 편집은 Canvas 측 포커스 아웃 / ESC 에서 종료

    def commit_active(self, scene: AnnotationScene) -> None:
        """현재 편집 중 텍스트를 확정. 빈 텍스트면 제거."""
        if self._active is None:
            return
        self._active.exit_edit_mode()
        if self._active.text().strip() == "":
            scene.remove_annotation(self._active)
        self._active = None

    def deactivated(self, scene: AnnotationScene) -> None:
        self.commit_active(scene)

    def double_click(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        # 선택 도구에서 더블클릭이 들어와도 TextAnnotationItem 위면 재편집
        for it in scene.items(scene_pos):
            if isinstance(it, TextAnnotationItem):
                it.enter_edit_mode()
                self._active = it
                return
