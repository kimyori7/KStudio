"""Frameless QMainWindow에 변/모서리 리사이즈를 추가하는 헬퍼.

QMainWindow.installEventFilter() 로 부착해서 사용한다.
"""
from __future__ import annotations
from PySide6.QtCore import QObject, QEvent, Qt, QPoint, QRect
from PySide6.QtGui import QCursor


class FramelessResizer(QObject):
    """창 가장자리 N 픽셀 안에서 마우스를 받아 리사이즈를 처리."""

    def __init__(self, window, grip: int = 6, min_w: int = 480, min_h: int = 360):
        super().__init__(window)
        self.window = window
        self.grip = grip
        self.min_w = min_w
        self.min_h = min_h

        self._drag_edge: str | None = None
        self._drag_origin: QPoint | None = None
        self._drag_start_geom: QRect | None = None

        # 메인 윈도우와 모든 자식 위젯에서 마우스 이동을 받기 위해
        window.setMouseTracking(True)
        window.installEventFilter(self)

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            edge = self._edge_at(event.globalPosition().toPoint())
            if edge:
                self._drag_edge = edge
                self._drag_origin = event.globalPosition().toPoint()
                self._drag_start_geom = self.window.geometry()
                return True
        elif et == QEvent.MouseMove:
            if self._drag_edge is not None:
                self._do_resize(event.globalPosition().toPoint())
                return True
            else:
                # 가장자리 hover시 커서 변경 (하지만 자식 위젯이 자체 커서를 잡으면 우선)
                edge = self._edge_at(event.globalPosition().toPoint())
                if edge:
                    self.window.setCursor(self._cursor_for(edge))
                else:
                    self.window.unsetCursor()
        elif et == QEvent.MouseButtonRelease and self._drag_edge is not None:
            self._drag_edge = None
            self._drag_origin = None
            self._drag_start_geom = None
            self.window.unsetCursor()
            return True
        return False

    def _edge_at(self, gpos: QPoint) -> str | None:
        if self.window.isMaximized() or self.window.isFullScreen():
            return None
        g = self.window.geometry()
        x, y = gpos.x() - g.x(), gpos.y() - g.y()
        w, h = g.width(), g.height()
        gp = self.grip
        if x < 0 or y < 0 or x >= w or y >= h:
            return None
        left = x < gp
        right = x > w - gp
        top = y < gp
        bottom = y > h - gp
        if top and left:    return "nw"
        if top and right:   return "ne"
        if bottom and left: return "sw"
        if bottom and right:return "se"
        if left:   return "w"
        if right:  return "e"
        if top:    return "n"
        if bottom: return "s"
        return None

    def _cursor_for(self, edge: str) -> QCursor:
        return QCursor({
            "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
            "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor,
            "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
            "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
        }[edge])

    def _do_resize(self, gpos: QPoint) -> None:
        if self._drag_origin is None or self._drag_start_geom is None:
            return
        delta = gpos - self._drag_origin
        dx, dy = delta.x(), delta.y()
        g = self._drag_start_geom
        nx, ny, nw, nh = g.x(), g.y(), g.width(), g.height()
        e = self._drag_edge
        if "w" in e:
            cap = g.right() - self.min_w + 1
            nx = min(cap, g.x() + dx)
            nw = g.width() - (nx - g.x())
        if "e" in e:
            nw = max(self.min_w, g.width() + dx)
        if "n" in e:
            cap = g.bottom() - self.min_h + 1
            ny = min(cap, g.y() + dy)
            nh = g.height() - (ny - g.y())
        if "s" in e:
            nh = max(self.min_h, g.height() + dy)
        self.window.setGeometry(nx, ny, nw, nh)
