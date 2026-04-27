"""편집 캔버스 — QGraphicsView 래퍼.

책임:
- 현재 도구를 보유하고 마우스/키 이벤트를 Tool 로 위임
- 줌(Fit/100%/Ctrl+Wheel) 처리
- 씬 렌더링 → QImage (저장용)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QGraphicsView

from .scene import AnnotationScene
from .tools.base import Tool
from .tools.select import SelectTool

ZOOM_MIN = 0.25
ZOOM_MAX = 4.0
ZOOM_STEP = 1.15


class AnnotationCanvas(QGraphicsView):
    tool_mouse_pressed = Signal()  # Undo 커맨드 그룹핑 힌트용 (Task 18에서 활용)

    def __init__(self, background: QImage) -> None:
        self._scene = AnnotationScene(background)
        super().__init__(self._scene)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.StrongFocus)

        self._tool: Tool = SelectTool()
        self._shift_held = False
        self._undo_stack = None

    # --- scene proxy ---
    def scene(self) -> AnnotationScene:
        return self._scene

    def render_composite(self) -> QImage:
        return self._scene.render_composite()

    # --- tool ---
    def set_tool(self, tool: Tool) -> None:
        if self._tool is tool:
            return
        self._tool.deactivated(self._scene)
        self._tool = tool
        self._tool.activated(self._scene)

    def current_tool(self) -> Tool:
        return self._tool

    def shift_held(self) -> bool:
        return self._shift_held

    def set_undo_stack(self, stack) -> None:
        self._undo_stack = stack

    def undo_stack(self):
        return self._undo_stack

    def _delete_selected(self) -> None:
        from .commands import RemoveAnnotationCommand
        if self._undo_stack is None:
            return
        for it in self._scene.annotations():
            if it.isSelected():
                self._undo_stack.push(RemoveAnnotationCommand(self._scene, it))
                return  # 단일 선택이라 하나만

    # --- zoom ---
    def set_fit_mode(self) -> None:
        br = self._scene.sceneRect()
        self.fitInView(br, Qt.KeepAspectRatio)
        if self.transform().m11() > 1.0:
            self.resetTransform()  # 작은 이미지는 100% 유지

    def set_hundred_percent_mode(self) -> None:
        self.resetTransform()

    def set_zoom_factor(self, factor: float) -> None:
        factor = max(ZOOM_MIN, min(ZOOM_MAX, factor))
        self.resetTransform()
        self.scale(factor, factor)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            factor = ZOOM_STEP if delta > 0 else 1.0 / ZOOM_STEP
            current = self.transform().m11()
            target = current * factor
            self.set_zoom_factor(target)
            event.accept()
            return
        super().wheelEvent(event)

    # --- event → tool dispatch ---
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and not isinstance(self._tool, SelectTool):
            scene_pos = self.mapToScene(event.pos())
            self._tool.mouse_press(self._scene, scene_pos)
            event.accept()
            return
        # SelectTool 인 경우 Qt 의 기본 클릭/드래그 선택 동작을 그대로 사용
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not isinstance(self._tool, SelectTool):
            scene_pos = self.mapToScene(event.pos())
            self._tool.mouse_move(self._scene, scene_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and not isinstance(self._tool, SelectTool):
            scene_pos = self.mapToScene(event.pos())
            self._tool.mouse_release(self._scene, scene_pos)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        scene_pos = self.mapToScene(event.pos())
        self._tool.double_click(self._scene, scene_pos)
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Shift:
            self._shift_held = True
        elif event.key() == Qt.Key_Escape:
            self._tool.key_escape(self._scene)
        elif event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._delete_selected()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Shift:
            self._shift_held = False
        super().keyReleaseEvent(event)
