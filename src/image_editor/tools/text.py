"""텍스트 도구 — 클릭 위치에 빈 텍스트 박스 생성 + 편집 모드.

주의: AnnotationLayer 의 scene 은 픽스맵으로 렌더되어 캔버스에 표시될 뿐, 실제로 어떤
QGraphicsView 도 그 scene 을 바라보지 않는다. 그래서 TextAnnotationItem 을
AnnotationLayer scene 에 추가하고 setFocus 해도 키보드 입력이 도달하지 못해 글자가
입력되지 않는다. 우회: 편집 중에는 캔버스의 메인 scene(=뷰가 실제로 보고 있는 scene)
에 아이템을 둬서 키보드/포커스가 닿게 하고, 편집 종료(commit) 시점에 AnnotationLayer
scene 으로 옮긴다.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QUndoStack
from PySide6.QtWidgets import QGraphicsScene

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
        live_scene: QGraphicsScene,
        on_commit: Callable[[], None] | None = None,
    ) -> None:
        self._color = QColor(color)
        self._undo_stack = undo_stack
        # live_scene = 캔버스 뷰가 실제로 표시하는 메인 scene. 편집 중인 텍스트를 여기에
        # 두어야 키보드 포커스/입력이 도달한다.
        self._live_scene = live_scene
        self._on_commit = on_commit  # 편집 완료 후 외부(viewer)가 select 도구 복귀 등에 사용
        self._active: Optional[TextAnnotationItem] = None

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)

    def mouse_press(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        # 다른 텍스트를 편집 중이었다면 먼저 확정 — 단, 콜백은 호출하지 않음.
        # 사용자는 "또 다른 텍스트 박스를 만들겠다" 는 의도로 새 위치를 클릭한 것이므로
        # 도구 전환을 일으키지 않아야 한다. ESC/focusOut 으로 빠질 때만 콜백 발화.
        self.commit_active(scene, fire_callback=False)
        t = TextAnnotationItem(scene_pos, "", self._color)
        # 핵심: AnnotationLayer scene 이 아니라 메인(live) scene 에 넣는다 — 그래야
        # 캔버스 뷰가 키보드 이벤트를 이 아이템에 전달. 메인 scene 의 레이어 픽스맵
        # 들은 z = 0..N 이므로 편집 중 텍스트가 가려지지 않게 충분히 높은 z 부여.
        t.setZValue(1e6)
        self._live_scene.addItem(t)
        # 텍스트가 ESC 또는 focus 상실로 편집 종료될 때 자동으로 commit_active 호출되게 연결.
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
        # 편집 중에는 live scene 에 있었으므로 거기서 빼낸다.
        cur_scene = active.scene()
        if cur_scene is not None:
            cur_scene.removeItem(active)
        # 편집용으로 부풀려뒀던 z 를 기본값으로 복원.
        active.setZValue(0)
        if active.text().strip() != "":
            # 빈 텍스트가 아니면 AnnotationLayer scene 에 영구 등록 (Undo 가능).
            self._undo_stack.push(AddAnnotationCommand(scene, active))
        if fire_callback and self._on_commit is not None:
            self._on_commit()

    def deactivated(self, scene: AnnotationScene) -> None:
        # 다른 도구로 전환되면서 호출됨 — _on_commit 은 이미 도구 전환 중이라 무의미.
        if self._active is None:
            return
        active = self._active
        self._active = None
        active.on_edit_finished = None
        active.exit_edit_mode()
        cur_scene = active.scene()
        if cur_scene is not None:
            cur_scene.removeItem(active)
        active.setZValue(0)
        if active.text().strip() != "":
            self._undo_stack.push(AddAnnotationCommand(scene, active))

    def double_click(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        # 기존 텍스트 재편집 — annotation scene 에서 꺼내 live scene 으로 옮긴 뒤 편집.
        for it in scene.items(scene_pos):
            if isinstance(it, TextAnnotationItem):
                scene.removeItem(it)
                it.setZValue(1e6)
                self._live_scene.addItem(it)
                it.on_edit_finished = lambda: self.commit_active(scene)
                it.enter_edit_mode()
                self._active = it
                return
