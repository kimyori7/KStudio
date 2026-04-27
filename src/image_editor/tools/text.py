"""텍스트 도구 — 클릭 위치에 빈 텍스트 박스 생성 + 편집 모드."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QUndoStack

from ..commands import AddAnnotationCommand
from ..items.text import TextAnnotationItem
from ..scene import AnnotationScene
from .base import Tool


class TextTool(Tool):
    name = "text"

    def __init__(
        self,
        color: QColor,
        undo_stack: QUndoStack,
        on_commit: Callable[[], None] | None = None,
    ) -> None:
        self._color = QColor(color)
        self._undo_stack = undo_stack
        self._on_commit = on_commit  # 편집 완료 후 외부(viewer)가 select 도구 복귀 등에 사용
        self._active: TextAnnotationItem | None = None

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)

    def mouse_press(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        # 다른 텍스트를 편집 중이었다면 먼저 확정 — 단, 콜백은 호출하지 않음.
        # 사용자는 "또 다른 텍스트 박스를 만들겠다" 는 의도로 새 위치를 클릭한 것이므로
        # 도구 전환을 일으키지 않아야 한다. ESC/focusOut 으로 빠질 때만 콜백 발화.
        self.commit_active(scene, fire_callback=False)
        t = TextAnnotationItem(scene_pos, "", self._color)
        scene.add_annotation(t)
        # 텍스트가 ESC 또는 focus 상실로 편집 종료될 때 자동으로 commit_active 호출되게 연결.
        # commit_active 안에서 self._active = None 후 exit_edit_mode 다시 호출하지만,
        # exit_edit_mode 가 이미 NoTextInteraction 이면 콜백 재호출 안 함 (재진입 방지).
        t.on_edit_finished = lambda: self.commit_active(scene)
        t.enter_edit_mode()
        self._active = t

    def mouse_release(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        pass

    def commit_active(self, scene: AnnotationScene, fire_callback: bool = True) -> None:
        if self._active is None:
            return
        active = self._active
        self._active = None
        # 콜백 재호출 방지 — exit_edit_mode 호출 전에 분리
        active.on_edit_finished = None
        active.exit_edit_mode()
        if active.text().strip() == "":
            scene.remove_annotation(active)
        else:
            # 텍스트는 mouse_press 시 이미 scene 에 추가됨 — 일단 제거 후 AddAnnotationCommand 로 재추가 (Undo 가능)
            scene.remove_annotation(active)
            self._undo_stack.push(AddAnnotationCommand(scene, active))
        if fire_callback and self._on_commit is not None:
            self._on_commit()

    def deactivated(self, scene: AnnotationScene) -> None:
        # 다른 도구로 전환되면서 호출됨 — _on_commit 은 이미 도구 전환 중이라 무의미.
        # commit 만 하고 콜백은 부르지 않음.
        if self._active is None:
            return
        active = self._active
        self._active = None
        active.on_edit_finished = None
        active.exit_edit_mode()
        if active.text().strip() == "":
            scene.remove_annotation(active)
        else:
            scene.remove_annotation(active)
            self._undo_stack.push(AddAnnotationCommand(scene, active))

    def double_click(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        for it in scene.items(scene_pos):
            if isinstance(it, TextAnnotationItem):
                it.on_edit_finished = lambda: self.commit_active(scene)
                it.enter_edit_mode()
                self._active = it
                return
