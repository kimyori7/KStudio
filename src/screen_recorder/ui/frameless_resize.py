"""Frameless QMainWindow에 변/모서리 리사이즈를 추가하는 헬퍼.

QApplication에 이벤트 필터를 설치해서 모든 자식 위젯의 마우스 이동도 가로챈다.
(QMainWindow에만 설치하면 자식 위젯들이 이벤트를 먼저 소비해서 가장자리 감지가 실패함.)
"""
from __future__ import annotations
from PySide6.QtCore import QObject, QEvent, Qt, QPoint, QRect
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication


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
        self._cursor_active = False

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    # ---------- 헬퍼 ----------

    def _belongs_to_window(self, widget) -> bool:
        """이벤트 대상 위젯이 우리 윈도우의 자식인지 확인."""
        if widget is None:
            return False
        try:
            return widget.window() is self.window
        except Exception:
            return False

    def _restore_cursor(self) -> None:
        if self._cursor_active:
            QApplication.restoreOverrideCursor()
            self._cursor_active = False

    def _set_cursor(self, edge: str) -> None:
        c = self._cursor_for(edge)
        if not self._cursor_active:
            QApplication.setOverrideCursor(c)
            self._cursor_active = True
        else:
            QApplication.changeOverrideCursor(c)

    # ---------- 이벤트 필터 ----------

    def eventFilter(self, obj, event):
        et = event.type()
        # 드래그 중에는 모든 마우스 이벤트를 우리가 처리
        if self._drag_edge is not None:
            if et == QEvent.MouseMove:
                self._do_resize(QCursor.pos())
                return True
            if et == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._drag_edge = None
                self._drag_origin = None
                self._drag_start_geom = None
                self._restore_cursor()
                return True

        # 우리 윈도우에 속한 위젯의 이벤트만 관심
        if et in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.HoverMove, QEvent.Enter, QEvent.Leave):
            if not self._belongs_to_window(obj):
                return False
            edge = self._edge_at(QCursor.pos())
            if et == QEvent.MouseButtonPress and edge and getattr(event, "button", lambda: None)() == Qt.LeftButton:
                self._drag_edge = edge
                self._drag_origin = QCursor.pos()
                self._drag_start_geom = self.window.geometry()
                self._set_cursor(edge)
                return True
            # hover/move 시 커서 갱신
            if edge:
                self._set_cursor(edge)
            else:
                self._restore_cursor()
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
