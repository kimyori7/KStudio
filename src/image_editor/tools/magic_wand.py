"""MagicWandTool — 클릭한 색과 유사한 영역을 마스크에서 제거.

심플 BFS flood-fill (4-neighborhood). 클릭 시 click_at 시그널이
(QPoint, tolerance) 로 발화됨. 실제 플러드-필 + 마스크 적용은
MagicWandCommand 가 처리.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QPointF, Signal
from PySide6.QtWidgets import QGraphicsScene

from .base import Tool


class _Emitter(QObject):
    click_at = Signal(QPoint, int)   # (scene 좌표, tolerance)


class MagicWandTool(Tool):
    name = "magic_wand"

    def __init__(self, tolerance: int = 32) -> None:
        super().__init__()
        self.tolerance = tolerance
        self._emitter = _Emitter()
        self.click_at = self._emitter.click_at

    def mouse_press(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        pt = QPoint(int(scene_pos.x()), int(scene_pos.y()))
        self._emitter.click_at.emit(pt, self.tolerance)
