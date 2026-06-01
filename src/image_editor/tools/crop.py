"""CropTool — 사각형 오버레이 도구 (8 핸들 인터랙티브).

활성화 시 캔버스 전체를 덮는 반투명 오버레이가 생기고, 드래그로 사각형 범위를
지정한 뒤 Enter 로 commit_requested 시그널을 보낸다. Esc 는 취소.

처음 드래그가 끝나면 사각형 4 모서리 + 4 가장자리에 핸들이 생긴다.
- 핸들에 hover 시 cursor 가 방향에 맞게 변경.
- 핸들 드래그 시 해당 면/모서리만 이동.
- 빈 공간 드래그 시 사각형 전체 이동.

실제 자르기 동작(Layer 잘라내기)은 CropCommand 가 담당하며, 이 도구는 단순히
사용자 의도(rect)를 신호로만 전달한다.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsRectItem,
    QGraphicsScene,
)

from .base import Tool
from .crop_magnifier import CropMagnifier, loupe_position


# 핸들 식별자 — (수직, 수평) 위치
_H_NW, _H_N, _H_NE = "nw", "n", "ne"
_H_W,  _H_INSIDE, _H_E  = "w",  "in", "e"
_H_SW, _H_S, _H_SE = "sw", "s", "se"
_HANDLE_IDS = (_H_NW, _H_N, _H_NE, _H_W, _H_E, _H_SW, _H_S, _H_SE)

_HANDLE_CURSORS = {
    _H_NW: Qt.SizeFDiagCursor,
    _H_SE: Qt.SizeFDiagCursor,
    _H_NE: Qt.SizeBDiagCursor,
    _H_SW: Qt.SizeBDiagCursor,
    _H_N: Qt.SizeVerCursor,
    _H_S: Qt.SizeVerCursor,
    _H_W: Qt.SizeHorCursor,
    _H_E: Qt.SizeHorCursor,
}

# scene 좌표 기준 — 모서리/가장자리 핸들의 한 변 길이.
_CORNER_SIZE = 12.0
_EDGE_SIZE = 8.0
# 빈 영역(테두리·내부)에서 hover 했을 때 핸들로 인식할 여유 폭.
_EDGE_PICK_TOL = 6.0
_CORNER_HANDLES = (_H_NW, _H_NE, _H_SW, _H_SE)


class _OverlayItem(QGraphicsRectItem):
    """실선 테두리 + 반투명 검정 채움의 단순 사각형 (selection 의 marching ants 와
    구분되도록 실선)."""

    def __init__(self) -> None:
        super().__init__()
        pen = QPen(QColor(255, 220, 60))    # 노란빛 — 크롭은 '잘리는 영역'이라 selection 과 다른 색
        pen.setWidth(2)
        pen.setCosmetic(True)
        pen.setStyle(Qt.SolidLine)
        self.setPen(pen)
        self.setBrush(QColor(0, 0, 0, 80))
        self.setZValue(10_000)


class _HandleItem(QGraphicsRectItem):
    """모서리/가장자리 핸들 — 흰 채움 + 검정 테두리. 모서리는 더 굵게 보이도록 별도로 처리."""

    def __init__(self, *, corner: bool = False) -> None:
        super().__init__()
        pen = QPen(QColor(0, 0, 0))
        # 모서리(corner) 핸들은 가장자리(edge) 핸들보다 더 굵은 테두리.
        pen.setWidth(2 if corner else 1)
        pen.setCosmetic(True)
        self.setPen(pen)
        # 모서리는 노란빛으로 더 강조.
        self.setBrush(QBrush(QColor(255, 220, 60) if corner else QColor(255, 255, 255)))
        self.setZValue(10_001)


class _ToolEmitter(QObject):
    """Tool 자체가 QObject 가 아니므로 시그널 송출용 헬퍼."""

    commit_requested = Signal(QRect)
    cancelled = Signal()
    cursor_requested = Signal(int)  # Qt.CursorShape 값


class CropTool(Tool):
    name = "crop"

    def __init__(self) -> None:
        super().__init__()
        self._emitter = _ToolEmitter()
        # 외부에서 tool.commit_requested.connect(...) 형태로 쓸 수 있도록 노출.
        self.commit_requested = self._emitter.commit_requested
        self.cancelled = self._emitter.cancelled
        self.cursor_requested = self._emitter.cursor_requested
        self._overlay: Optional[_OverlayItem] = None
        self._scene: Optional[QGraphicsScene] = None
        self._handles: dict[str, _HandleItem] = {}
        self._dragging = False
        self._drag_handle: Optional[str] = None
        self._press_pos: Optional[QPointF] = None
        # 핸들 드래그 시작 시점의 사각형 (드래그 동안 보존)
        self._press_rect: Optional[QRectF] = None
        self._committed = False
        # rect 가 한 번이라도 정의된 후엔 핸들 모드.
        self._has_rect = False
        # 돋보기(확대경) — 뷰가 있을 때만 생성됨.
        self._mag: CropMagnifier | None = None
        self._view = None

    # --- Tool API ---
    def activated(self, scene: QGraphicsScene) -> None:
        self._scene = scene
        self._committed = False
        self._has_rect = False
        if self._overlay is None:
            self._overlay = _OverlayItem()
            # 활성화 직후엔 영역 미지정 — 사용자가 드래그해야 사각형이 생김.
            self._overlay.setRect(QRectF())
            scene.addItem(self._overlay)
        # 돋보기 — scene 의 첫 view(LayerCanvas)가 있고 composite 가능할 때만.
        # headless(뷰 없음) 에선 _mag=None 으로 두어 크롭만 정상 동작.
        self._view = None
        self._mag = None
        views = scene.views()
        view = views[0] if views else None
        composite = getattr(view, "composite", None)
        if view is not None and callable(composite):
            self._view = view
            self._mag = CropMagnifier(view.viewport())
            self._mag.set_source(view.composite())

    def deactivated(self, scene: QGraphicsScene) -> None:
        if self._overlay is not None and self._overlay.scene() is scene:
            scene.removeItem(self._overlay)
        self._overlay = None
        self._remove_handles(scene)
        self._scene = None
        self._dragging = False
        self._drag_handle = None
        self._press_pos = None
        self._press_rect = None
        self._has_rect = False
        # 돋보기 제거 — 위젯 + composite 스냅샷(4K~33MB) 메모리 해제.
        if self._mag is not None:
            self._mag.hide()
            self._mag.setParent(None)
            self._mag.deleteLater()
            self._mag = None
        self._view = None

    # --- 외부에서 조회 가능한 상태 ---
    def current_rect(self) -> QRect:
        if self._overlay is None:
            return QRect()
        r = self._overlay.rect()
        return QRect(int(r.x()), int(r.y()), int(r.width()), int(r.height()))

    def is_committed_or_cancelled(self) -> bool:
        # commit 후엔 _committed=True, cancel 후엔 overlay/_scene 둘 다 None.
        return self._committed or (self._overlay is None and self._scene is None)

    # --- 핸들 ---
    def _ensure_handles(self, scene: QGraphicsScene) -> None:
        if self._handles:
            return
        for hid in _HANDLE_IDS:
            h = _HandleItem(corner=hid in _CORNER_HANDLES)
            scene.addItem(h)
            self._handles[hid] = h

    def _remove_handles(self, scene: QGraphicsScene) -> None:
        for hid, h in list(self._handles.items()):
            if h.scene() is scene:
                scene.removeItem(h)
        self._handles.clear()

    def _layout_handles(self) -> None:
        if self._overlay is None or not self._handles:
            return
        r = self._overlay.rect()
        positions = {
            _H_NW: (r.left(),                r.top()),
            _H_N:  (r.left() + r.width() / 2, r.top()),
            _H_NE: (r.right(),               r.top()),
            _H_W:  (r.left(),                r.top() + r.height() / 2),
            _H_E:  (r.right(),               r.top() + r.height() / 2),
            _H_SW: (r.left(),                r.bottom()),
            _H_S:  (r.left() + r.width() / 2, r.bottom()),
            _H_SE: (r.right(),               r.bottom()),
        }
        for hid, (cx, cy) in positions.items():
            s = _CORNER_SIZE if hid in _CORNER_HANDLES else _EDGE_SIZE
            self._handles[hid].setRect(QRectF(cx - s / 2, cy - s / 2, s, s))

    def _hit_handle(self, scene_pos: QPointF) -> Optional[str]:
        """scene_pos 가 어떤 핸들 영역 안에 있는지 반환. 가장자리/모서리 픽 허용."""
        if self._overlay is None or not self._has_rect:
            return None
        r = self._overlay.rect()
        x, y = scene_pos.x(), scene_pos.y()
        tol = _EDGE_PICK_TOL
        near_left   = abs(x - r.left())   <= tol
        near_right  = abs(x - r.right())  <= tol
        near_top    = abs(y - r.top())    <= tol
        near_bottom = abs(y - r.bottom()) <= tol
        within_x = r.left() - tol <= x <= r.right() + tol
        within_y = r.top()  - tol <= y <= r.bottom() + tol
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
        if r.contains(scene_pos):
            return _H_INSIDE
        return None

    def _update_magnifier(self, scene_pos: QPointF) -> None:
        """돋보기 위치/중앙픽셀/라벨 갱신. 뷰 없으면 no-op(headless)."""
        if self._mag is None or self._view is None or self._overlay is None:
            return
        vp = self._view.mapFromScene(scene_pos)
        vp_w = self._view.viewport().width()
        vp_h = self._view.viewport().height()
        x, y = loupe_position(vp.x(), vp.y(), vp_w, vp_h)
        self._mag.move(x, y)
        r = self._overlay.rect()
        rect_size = (
            QSize(round(r.width()), round(r.height()))
            if r.width() >= 1 and r.height() >= 1 else None
        )
        self._mag.update_at(scene_pos.toPoint(), rect_size)
        # show()/raise_() 는 숨김→보임 전환 시 1회만 (매 move Z-order 연산 절약).
        if not self._mag.isVisible():
            self._mag.show()
            self._mag.raise_()

    # --- Mouse (modifiers 인자 없음 — Tool 베이스 시그니처에 맞춤) ---
    def mouse_press(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        if self._overlay is None:
            return
        if self._has_rect:
            hit = self._hit_handle(scene_pos)
            if hit is not None:
                self._dragging = True
                self._drag_handle = hit
                self._press_pos = QPointF(scene_pos)
                self._press_rect = QRectF(self._overlay.rect())
                return
            # 빈 곳 누름 → 새 사각형 시작.
            self._has_rect = False
            self._remove_handles(scene)
        self._press_pos = QPointF(scene_pos)
        self._dragging = True
        self._drag_handle = None
        self._overlay.setRect(QRectF(scene_pos, scene_pos))

    def mouse_move(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        if self._overlay is None:
            return
        if not self._dragging:
            # 드래그 중이 아니면 hover cursor 만 갱신.
            if self._has_rect:
                hit = self._hit_handle(scene_pos)
                shape = (
                    Qt.SizeAllCursor if hit == _H_INSIDE else
                    _HANDLE_CURSORS.get(hit) if hit is not None else
                    Qt.CrossCursor
                )
                self.cursor_requested.emit(shape.value)
            self._update_magnifier(scene_pos)
            return
        if self._drag_handle is None or not self._has_rect:
            # 새 사각형 그리기 모드
            assert self._press_pos is not None
            rect = QRectF(self._press_pos, scene_pos).normalized()
            modifiers = QApplication.keyboardModifiers()
            if modifiers & Qt.ShiftModifier:
                side = max(rect.width(), rect.height())
                rect = QRectF(rect.topLeft(), rect.topLeft() + QPointF(side, side))
            rect = rect.intersected(scene.sceneRect())
            self._overlay.setRect(rect)
        else:
            # 핸들 드래그 모드 — _press_rect 기준으로 변형.
            assert self._press_pos is not None and self._press_rect is not None
            dx = scene_pos.x() - self._press_pos.x()
            dy = scene_pos.y() - self._press_pos.y()
            new_rect = self._apply_handle_drag(self._press_rect, self._drag_handle, dx, dy)
            new_rect = new_rect.normalized().intersected(scene.sceneRect())
            # 너무 0 크기로 줄어드는 것 방지.
            if new_rect.width() < 1:
                new_rect.setWidth(1.0)
            if new_rect.height() < 1:
                new_rect.setHeight(1.0)
            self._overlay.setRect(new_rect)
            self._layout_handles()
        # 사각형 갱신 후 돋보기(위치 + 크기 라벨) 갱신.
        self._update_magnifier(scene_pos)

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

    def mouse_release(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        if not self._dragging or self._overlay is None or self._press_pos is None:
            self._dragging = False
            self._drag_handle = None
            self._press_pos = None
            self._press_rect = None
            return
        if self._drag_handle is None:
            # 새 그리기 모드 — release 위치까지 반영
            rect = QRectF(self._press_pos, scene_pos).normalized()
            modifiers = QApplication.keyboardModifiers()
            if modifiers & Qt.ShiftModifier:
                side = max(rect.width(), rect.height())
                rect = QRectF(rect.topLeft(), rect.topLeft() + QPointF(side, side))
            rect = rect.intersected(scene.sceneRect())
            self._overlay.setRect(rect)
            if rect.width() >= 2 and rect.height() >= 2:
                self._has_rect = True
                self._ensure_handles(scene)
                self._layout_handles()
        else:
            # 핸들 드래그 종료 — rect 는 이미 mouse_move 에서 갱신됨, 핸들 위치만 정리.
            self._layout_handles()
        self._dragging = False
        self._drag_handle = None
        self._press_pos = None
        self._press_rect = None

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
