"""CropTool — 사각형 오버레이 도구.

활성화 시 캔버스 전체를 덮는 반투명 오버레이가 생기고, 드래그로 사각형 범위를
지정한 뒤 Enter 로 commit_requested 시그널을 보낸다. Esc 는 취소.

실제 자르기 동작(Layer 잘라내기)은 CropCommand 가 담당하며, 이 도구는 단순히
사용자 의도(rect)를 신호로만 전달한다.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsRectItem,
    QGraphicsScene,
)

from .base import Tool


class _OverlayItem(QGraphicsRectItem):
    """대시 테두리 + 반투명 검정 채움의 단순 사각형."""

    def __init__(self) -> None:
        super().__init__()
        pen = QPen(QColor(255, 255, 255))
        pen.setWidth(0)  # cosmetic — 줌과 무관하게 1픽셀
        pen.setStyle(Qt.DashLine)
        self.setPen(pen)
        self.setBrush(QColor(0, 0, 0, 80))
        self.setZValue(10_000)


class _ToolEmitter(QObject):
    """Tool 자체가 QObject 가 아니므로 시그널 송출용 헬퍼."""

    commit_requested = Signal(QRect)
    cancelled = Signal()


class CropTool(Tool):
    name = "crop"

    def __init__(self) -> None:
        super().__init__()
        self._emitter = _ToolEmitter()
        # 외부에서 tool.commit_requested.connect(...) 형태로 쓸 수 있도록 노출.
        self.commit_requested = self._emitter.commit_requested
        self.cancelled = self._emitter.cancelled
        self._overlay: Optional[_OverlayItem] = None
        self._scene: Optional[QGraphicsScene] = None
        self._dragging = False
        self._press_pos: Optional[QPointF] = None
        self._committed = False

    # --- Tool API ---
    def activated(self, scene: QGraphicsScene) -> None:
        self._scene = scene
        self._committed = False
        if self._overlay is None:
            self._overlay = _OverlayItem()
            self._overlay.setRect(scene.sceneRect())
            scene.addItem(self._overlay)

    def deactivated(self, scene: QGraphicsScene) -> None:
        if self._overlay is not None and self._overlay.scene() is scene:
            scene.removeItem(self._overlay)
        self._overlay = None
        self._scene = None
        self._dragging = False
        self._press_pos = None

    # --- 외부에서 조회 가능한 상태 ---
    def current_rect(self) -> QRect:
        if self._overlay is None:
            return QRect()
        r = self._overlay.rect()
        return QRect(int(r.x()), int(r.y()), int(r.width()), int(r.height()))

    def is_committed_or_cancelled(self) -> bool:
        # commit 후엔 _committed=True, cancel 후엔 overlay/_scene 둘 다 None.
        return self._committed or (self._overlay is None and self._scene is None)

    # --- Mouse (modifiers 인자 없음 — Tool 베이스 시그니처에 맞춤) ---
    def mouse_press(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        if self._overlay is None:
            return
        self._press_pos = QPointF(scene_pos)
        self._dragging = True
        self._overlay.setRect(QRectF(scene_pos, scene_pos))

    def mouse_move(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        if not self._dragging or self._overlay is None or self._press_pos is None:
            return
        rect = QRectF(self._press_pos, scene_pos).normalized()
        # Shift 누르면 정사각형 — Tool API 에 modifiers 인자가 없으므로
        # 그 시점의 modifier 상태를 QApplication 으로 직접 조회한다.
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.ShiftModifier:
            side = max(rect.width(), rect.height())
            rect = QRectF(rect.topLeft(), rect.topLeft() + QPointF(side, side))
        # 캔버스 영역 밖으로 못 벗어나도록 클램프
        rect = rect.intersected(scene.sceneRect())
        self._overlay.setRect(rect)

    def mouse_release(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        # 드래그 종료. mouse_move 가 한 번도 안 들어왔던 경우(테스트 등)를 위해
        # 마지막 위치로 사각형을 한 번 더 갱신한다.
        if self._dragging and self._overlay is not None and self._press_pos is not None:
            rect = QRectF(self._press_pos, scene_pos).normalized()
            modifiers = QApplication.keyboardModifiers()
            if modifiers & Qt.ShiftModifier:
                side = max(rect.width(), rect.height())
                rect = QRectF(rect.topLeft(), rect.topLeft() + QPointF(side, side))
            rect = rect.intersected(scene.sceneRect())
            self._overlay.setRect(rect)
        self._dragging = False

    # --- Keys ---
    def key_escape(self, scene: QGraphicsScene) -> None:
        if self._overlay is None:
            return
        self.deactivated(scene)
        self._emitter.cancelled.emit()

    def key_enter(self, scene: QGraphicsScene) -> None:
        if self._overlay is None:
            return
        r = self.current_rect()
        if r.width() <= 0 or r.height() <= 0:
            return
        self._committed = True
        self._emitter.commit_requested.emit(r)
