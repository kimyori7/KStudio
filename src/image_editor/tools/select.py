"""선택/이동 도구. 드래그 이동/리사이즈는 QGraphicsItem 기본 플래그로 처리됨."""
from __future__ import annotations

from PySide6.QtCore import QPointF

from ..scene import AnnotationScene
from .base import Tool


class SelectTool(Tool):
    name = "select"

    def mouse_press(self, scene, scene_pos: QPointF) -> None:
        # AnnotationLayer 가 아직 없는 캔버스에서는 _active_annotation_scene 이 None 을
        # 반환해 캔버스의 메인 scene(QGraphicsScene) 이 그대로 들어온다 — 주석 자체가
        # 없으니 select 동작은 no-op 으로 안전 종료.
        if not isinstance(scene, AnnotationScene):
            return
        # 클릭 위치의 최상위 주석 아이템 선택 (배경/핸들 제외)
        for it in scene.items(scene_pos):
            if it.parentItem() is not None:
                continue  # 핸들 또는 자식
            if it in scene.annotations():
                for other in scene.annotations():
                    if other is not it:
                        other.setSelected(False)
                it.setSelected(True)
                return
        # 빈 곳 클릭 — 전체 선택 해제
        for a in scene.annotations():
            a.setSelected(False)

    def key_escape(self, scene) -> None:
        if not isinstance(scene, AnnotationScene):
            return
        for a in scene.annotations():
            a.setSelected(False)
