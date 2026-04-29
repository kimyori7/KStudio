"""SelectionTool — 사각형 영역 선택 도구.

드래그로 선택 영역을 정의. 기존 selection 이 있을 때 모서리/가장자리 핸들을
드래그하면 영역이 변형된다. 빈 곳 클릭(또는 ESC) 시 선택 해제.
선택 결과는 SelectionModel 에 set_rect 으로 통보 → SelectionOverlay 가 자동 시각화.

다른 주석 도구들과 달리 scene 에 아이템을 추가하지 않는다. 시각은 오버레이가 담당.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtWidgets import QApplication, QGraphicsRectItem, QGraphicsScene
from PySide6.QtGui import QColor, QPen

from .base import Tool
from ..selection import SelectionModel


# 핸들 식별자 (CropTool 과 동일한 명명)
_H_NW, _H_N, _H_NE = "nw", "n", "ne"
_H_W,  _H_INSIDE, _H_E  = "w",  "in", "e"
_H_SW, _H_S, _H_SE = "sw", "s", "se"

_HANDLE_CURSORS = {
    _H_NW: Qt.SizeFDiagCursor, _H_SE: Qt.SizeFDiagCursor,
    _H_NE: Qt.SizeBDiagCursor, _H_SW: Qt.SizeBDiagCursor,
    _H_N: Qt.SizeVerCursor, _H_S: Qt.SizeVerCursor,
    _H_W: Qt.SizeHorCursor, _H_E: Qt.SizeHorCursor,
}
_EDGE_PICK_TOL = 6.0


class _ToolEmitter(QObject):
    cursor_requested = Signal(int)


class SelectionTool(Tool):
    name = "selection"

    def __init__(self, model: SelectionModel) -> None:
        super().__init__()
        self._model = model
        self._scene: Optional[QGraphicsScene] = None
        self._dragging = False
        self._drag_handle: Optional[str] = None
        self._press_pos: Optional[QPointF] = None
        # 핸들 드래그 시작 시점의 사각형 (드래그 동안 보존)
        self._press_rect: Optional[QRectF] = None
        # 드래그 중 라이브 미리보기용 임시 사각 (새로 그릴 때만 사용)
        self._preview: Optional[QGraphicsRectItem] = None
        self._emitter = _ToolEmitter()
        self.cursor_requested = self._emitter.cursor_requested

    def activated(self, scene: QGraphicsScene) -> None:
        self._scene = scene

    def deactivated(self, scene: QGraphicsScene) -> None:
        self._remove_preview()
        self._scene = None
        self._dragging = False
        self._drag_handle = None
        self._press_pos = None
        self._press_rect = None
        # 도구를 끄더라도 selection 은 유지 — 다른 도구로 가도 marching ants 는 보임.

    def _remove_preview(self) -> None:
        if self._preview is not None and self._scene is not None and self._preview.scene() is self._scene:
            self._scene.removeItem(self._preview)
        self._preview = None

    def _ensure_preview(self, scene: QGraphicsScene) -> None:
        if self._preview is None:
            self._preview = QGraphicsRectItem()
            pen = QPen(QColor(255, 255, 255))
            pen.setStyle(Qt.DashLine)
            pen.setWidth(0)
            pen.setCosmetic(True)
            self._preview.setPen(pen)
            self._preview.setBrush(Qt.NoBrush)
            self._preview.setZValue(99_998)
            scene.addItem(self._preview)

    def _hit_handle(self, scene_pos: QPointF) -> Optional[str]:
        """현재 selection 사각형 위 어떤 핸들을 가리키는지. 없으면 None."""
        rect = self._model.rect()
        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            return None
        rf = QRectF(rect)
        x, y = scene_pos.x(), scene_pos.y()
        tol = _EDGE_PICK_TOL
        near_left   = abs(x - rf.left())   <= tol
        near_right  = abs(x - rf.right())  <= tol
        near_top    = abs(y - rf.top())    <= tol
        near_bottom = abs(y - rf.bottom()) <= tol
        within_x = rf.left() - tol <= x <= rf.right() + tol
        within_y = rf.top()  - tol <= y <= rf.bottom() + tol
        if near_left and near_top and within_x and within_y:
            return _H_NW
        if near_right and near_top and within_x and within_y:
            return _H_NE
        if near_left and near_bottom and within_x and within_y:
            return _H_SW
        if near_right and near_bottom and within_x and within_y:
            return _H_SE
        if near_top and within_x:
            return _H_N
        if near_bottom and within_x:
            return _H_S
        if near_left and within_y:
            return _H_W
        if near_right and within_y:
            return _H_E
        if rf.contains(scene_pos):
            return _H_INSIDE
        return None

    @staticmethod
    def _apply_handle_drag(rect: QRectF, handle: str, dx: float, dy: float) -> QRectF:
        l, t, r, b = rect.left(), rect.top(), rect.right(), rect.bottom()
        if handle == _H_INSIDE:
            return rect.translated(dx, dy)
        if handle in (_H_NW, _H_W, _H_SW):
            l += dx
        if handle in (_H_NE, _H_E, _H_SE):
            r += dx
        if handle in (_H_NW, _H_N, _H_NE):
            t += dy
        if handle in (_H_SW, _H_S, _H_SE):
            b += dy
        return QRectF(l, t, r - l, b - t)

    def mouse_press(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        # 기존 selection 위 핸들/내부 hit 이면 변형 모드.
        hit = self._hit_handle(scene_pos)
        if hit is not None:
            self._dragging = True
            self._drag_handle = hit
            self._press_pos = QPointF(scene_pos)
            current = self._model.rect()
            self._press_rect = QRectF(current) if current is not None else None
            return
        # 그 외 → 새 사각형 그리기 모드.
        self._press_pos = QPointF(scene_pos)
        self._dragging = True
        self._drag_handle = None
        self._press_rect = None
        self._ensure_preview(scene)
        assert self._preview is not None
        self._preview.setRect(QRectF(scene_pos, scene_pos))

    def mouse_move(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        if not self._dragging:
            # hover cursor 갱신
            hit = self._hit_handle(scene_pos)
            if hit == _H_INSIDE:
                self.cursor_requested.emit(int(Qt.SizeAllCursor))
            elif hit is not None:
                self.cursor_requested.emit(int(_HANDLE_CURSORS[hit]))
            else:
                self.cursor_requested.emit(int(Qt.CrossCursor))
            return
        if self._press_pos is None:
            return
        if self._drag_handle is None:
            # 새로 그리는 중
            if self._preview is None:
                return
            rect = QRectF(self._press_pos, scene_pos).normalized()
            modifiers = QApplication.keyboardModifiers()
            if modifiers & Qt.ShiftModifier:
                side = max(rect.width(), rect.height())
                rect = QRectF(rect.topLeft(), rect.topLeft() + QPointF(side, side))
            rect = rect.intersected(scene.sceneRect())
            self._preview.setRect(rect)
        else:
            # 핸들 드래그 — 모델에 즉시 반영 (실시간 marching ants 갱신)
            if self._press_rect is None:
                return
            dx = scene_pos.x() - self._press_pos.x()
            dy = scene_pos.y() - self._press_pos.y()
            new_rect = self._apply_handle_drag(self._press_rect, self._drag_handle, dx, dy)
            new_rect = new_rect.normalized().intersected(scene.sceneRect())
            if new_rect.width() < 1 or new_rect.height() < 1:
                return
            qr = QRect(int(new_rect.x()), int(new_rect.y()),
                       int(new_rect.width()), int(new_rect.height()))
            self._model.set_rect(qr)

    def mouse_release(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        if not self._dragging or self._press_pos is None:
            self._remove_preview()
            self._dragging = False
            self._drag_handle = None
            self._press_rect = None
            return
        if self._drag_handle is None:
            # 새로 그리기 모드 — release 위치까지 반영 후 모델에 set
            rect = QRectF(self._press_pos, scene_pos).normalized()
            modifiers = QApplication.keyboardModifiers()
            if modifiers & Qt.ShiftModifier:
                side = max(rect.width(), rect.height())
                rect = QRectF(rect.topLeft(), rect.topLeft() + QPointF(side, side))
            rect = rect.intersected(scene.sceneRect())
            self._remove_preview()
            if rect.width() < 2 or rect.height() < 2:
                self._model.clear()
            else:
                qr = QRect(int(rect.x()), int(rect.y()),
                           int(rect.width()), int(rect.height()))
                self._model.set_rect(qr)
        # 핸들 드래그는 mouse_move 에서 이미 모델에 반영됨.
        self._dragging = False
        self._drag_handle = None
        self._press_pos = None
        self._press_rect = None

    def key_escape(self, scene: QGraphicsScene) -> None:
        if self._dragging:
            self._dragging = False
            self._drag_handle = None
            self._remove_preview()
            return
        self._model.clear()
