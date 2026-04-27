"""Tool 인터페이스 — 캔버스로부터 이벤트를 받아 주석 생성/선택/조작."""
from __future__ import annotations

from PySide6.QtCore import QPointF

from ..scene import AnnotationScene


class Tool:
    """모든 도구의 공통 인터페이스. 기본 구현은 빈 동작."""

    # 도구 이름 (단축키/툴바 매핑용)
    name: str = ""

    def activated(self, scene: AnnotationScene) -> None:
        """도구 선택되었을 때 호출."""
        pass

    def deactivated(self, scene: AnnotationScene) -> None:
        """도구 해제될 때 호출 (진행 중 드래그 취소 등)."""
        pass

    def mouse_press(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        pass

    def mouse_move(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        pass

    def mouse_release(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        pass

    def double_click(self, scene: AnnotationScene, scene_pos: QPointF) -> None:
        pass

    def key_escape(self, scene: AnnotationScene) -> None:
        """ESC 눌림. 드래그 중이면 취소, 아니면 선택 해제."""
        pass
