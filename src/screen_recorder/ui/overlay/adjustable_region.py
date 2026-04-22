"""사용자가 드래그/리사이즈로 조정하는 영역 테두리.

- 대기(standby): 녹색 실선 + 모서리 굵은 L자 + 라벨 ◇ 대기 중
- 영상 녹화: 빨강 실선 + 모서리 굵은 L자 + 라벨 ● REC hh:mm:ss
- GIF 녹화:  주황 "긴 선 + 짧은 간격" 점선 + 모서리 굵은 L자 + 라벨 ◆ GIF hh:mm:ss

대기 상태에서는 테두리/라벨 영역 클릭으로 이동·크기 조절 가능.
내부는 투명(클릭 통과)이라 아래 어플과 상호작용 가능.
녹화 상태에서는 전체 클릭 통과(움직임 봉인) + 화면 캡처 제외.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QRect, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QRegion
from PySide6.QtWidgets import QWidget


_COLOR_STANDBY = QColor("#2E7D32")
_COLOR_VIDEO = QColor("#E53935")
_COLOR_GIF = QColor("#FFB300")


class AdjustableRegionBorder(QWidget):
    rect_changed = Signal(int, int, int, int)  # x, y, w, h (geometry 변경)

    BORDER_THICKNESS = 4
    CORNER_THICKNESS = 8           # 모서리 L자 두께
    CORNER_LENGTH = 22             # 모서리 L자 길이
    LABEL_HEIGHT = 26              # 좌상단 라벨 영역 높이
    EDGE_GRIP = 8                  # 에지 리사이즈 감지 범위
    CORNER_GRIP = 16               # 코너 리사이즈 감지 범위 (대각선)
    MOVE_STRIP = 18                # 이동 드래그 가능한 테두리 폭
    MIN_SIZE = 80

    def __init__(self, initial_rect: tuple[int, int, int, int], mode: str = "video"):
        super().__init__()
        self.mode = mode              # "video" | "gif"
        self._state = "standby"       # "standby" | "recording"
        self._elapsed = 0
        self._drag_mode: str | None = None
        self._drag_origin = None
        self._drag_start_geom = None

        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        x, y, w, h = initial_rect
        w = max(self.MIN_SIZE, int(w))
        h = max(self.MIN_SIZE, int(h))
        self.setGeometry(int(x), int(y), w, h)

        self._sec_timer = QTimer(self)
        self._sec_timer.setInterval(1000)
        self._sec_timer.timeout.connect(self._tick_sec)

    # ---------- Public API (CaptureTarget 호환 일부) ----------

    def current_geometry(self) -> tuple[int, int, int, int]:
        return self.x(), self.y(), self.width(), self.height()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.update()

    def start_recording(self) -> None:
        self._state = "recording"
        self._elapsed = 0
        self._sec_timer.start()
        # 녹화 중에는 마우스 통과(프레임이 대상 어플의 클릭을 막지 않도록)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # 마스크 제거 (마우스는 어차피 통과; 시각적으로도 방해 없음)
        self.clearMask()
        self.update()

    def stop_recording(self) -> None:
        self._state = "standby"
        self._sec_timer.stop()
        self._elapsed = 0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._update_mask()
        self.update()

    def stop(self) -> None:
        """완전히 닫기."""
        self._sec_timer.stop()
        self.close()

    # ---------- 이벤트 ----------

    def showEvent(self, e):
        super().showEvent(e)
        self._update_mask()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_mask()

    def _update_mask(self):
        """대기 상태에서 테두리 영역만 마우스 받고, 내부는 클릭 통과."""
        if self._state == "recording":
            self.clearMask()
            return
        w, h = self.width(), self.height()
        ms = self.MOVE_STRIP
        lh = self.LABEL_HEIGHT
        full = QRegion(0, 0, w, h)
        # 내부 구멍(라벨 영역은 제외하고)
        hole_top = max(ms, lh)
        hole_x = ms
        hole_y = hole_top
        hole_w = max(0, w - 2 * ms)
        hole_h = max(0, h - hole_top - ms)
        if hole_w > 0 and hole_h > 0:
            hole = QRegion(hole_x, hole_y, hole_w, hole_h)
            self.setMask(full.subtracted(hole))
        else:
            self.setMask(full)

    def _hit_test(self, pos) -> str:
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        cg = self.CORNER_GRIP
        eg = self.EDGE_GRIP
        # 코너 먼저 (우선순위)
        if x < cg and y < cg: return "nw"
        if x > w - cg and y < cg: return "ne"
        if x < cg and y > h - cg: return "sw"
        if x > w - cg and y > h - cg: return "se"
        # 에지
        if x < eg: return "w"
        if x > w - eg: return "e"
        if y < eg: return "n"
        if y > h - eg: return "s"
        # 나머지(마스크 영역 안쪽): 이동
        return "move"

    def _cursor_for(self, mode: str):
        return {
            "move": Qt.SizeAllCursor,
            "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
            "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor,
            "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
            "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
        }.get(mode, Qt.ArrowCursor)

    def mousePressEvent(self, e):
        if self._state != "standby":
            return
        if e.button() == Qt.LeftButton:
            self._drag_mode = self._hit_test(e.position().toPoint())
            self._drag_origin = e.globalPosition().toPoint()
            self._drag_start_geom = self.geometry()

    def mouseMoveEvent(self, e):
        if self._state != "standby":
            return
        if self._drag_mode is None:
            mode = self._hit_test(e.position().toPoint())
            self.setCursor(self._cursor_for(mode))
            return
        delta = e.globalPosition().toPoint() - self._drag_origin
        g = self._drag_start_geom
        dx, dy = delta.x(), delta.y()
        ms = self.MIN_SIZE
        new_x, new_y, new_w, new_h = g.x(), g.y(), g.width(), g.height()
        m = self._drag_mode
        if m == "move":
            new_x = g.x() + dx
            new_y = g.y() + dy
        else:
            # 각 방향 처리
            if "w" in m:
                cap = g.right() - ms + 1
                new_x = min(cap, g.x() + dx)
                new_w = g.width() - (new_x - g.x())
            if "e" in m:
                new_w = max(ms, g.width() + dx)
            if "n" in m:
                cap = g.bottom() - ms + 1
                new_y = min(cap, g.y() + dy)
                new_h = g.height() - (new_y - g.y())
            if "s" in m:
                new_h = max(ms, g.height() + dy)
        self.setGeometry(new_x, new_y, new_w, new_h)

    def mouseReleaseEvent(self, e):
        if self._drag_mode is not None:
            self._drag_mode = None
            self.rect_changed.emit(self.x(), self.y(), self.width(), self.height())

    def _tick_sec(self):
        self._elapsed += 1
        self.update()

    # ---------- 그리기 ----------

    def _current_color_and_dash(self) -> tuple[QColor, list[int] | None]:
        if self._state == "standby":
            return _COLOR_STANDBY, None
        if self.mode == "gif":
            # 긴 선 + 짧은 간격 (모서리가 헷갈리지 않게)
            return _COLOR_GIF, [8, 2]
        return _COLOR_VIDEO, None

    def paintEvent(self, _):
        p = QPainter(self)
        color, dash = self._current_color_and_dash()

        w, h = self.width(), self.height()
        bt = self.BORDER_THICKNESS
        lh = self.LABEL_HEIGHT
        # 메인 사각 테두리 (라벨 영역 제외)
        pen = QPen(color, bt)
        if dash is not None:
            pen.setStyle(Qt.CustomDashLine)
            pen.setDashPattern(dash)
        else:
            pen.setStyle(Qt.SolidLine)
        pen.setCapStyle(Qt.FlatCap)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        border_rect = QRect(bt // 2, lh + bt // 2, w - bt, h - lh - bt)
        p.drawRect(border_rect)

        # 모서리 굵은 L자 마커 (상시 실선)
        corner_pen = QPen(color, self.CORNER_THICKNESS)
        corner_pen.setCapStyle(Qt.FlatCap)
        p.setPen(corner_pen)
        cl = self.CORNER_LENGTH
        t = self.CORNER_THICKNESS // 2
        rx0, ry0 = 0, lh
        rx1, ry1 = w - 1, h - 1
        # 좌상
        p.drawLine(rx0 + t, ry0 + t, rx0 + t + cl, ry0 + t)
        p.drawLine(rx0 + t, ry0 + t, rx0 + t, ry0 + t + cl)
        # 우상
        p.drawLine(rx1 - t - cl, ry0 + t, rx1 - t, ry0 + t)
        p.drawLine(rx1 - t, ry0 + t, rx1 - t, ry0 + t + cl)
        # 좌하
        p.drawLine(rx0 + t, ry1 - t - cl, rx0 + t, ry1 - t)
        p.drawLine(rx0 + t, ry1 - t, rx0 + t + cl, ry1 - t)
        # 우하
        p.drawLine(rx1 - t - cl, ry1 - t, rx1 - t, ry1 - t)
        p.drawLine(rx1 - t, ry1 - t - cl, rx1 - t, ry1 - t)

        # 라벨 배경 + 텍스트
        if self._state == "standby":
            label = f"◇ 대기 중  {w}×{h}"
        else:
            h_, rem = divmod(self._elapsed, 3600)
            m, s = divmod(rem, 60)
            prefix = "● REC" if self.mode == "video" else "◆ GIF"
            label = f"{prefix} {h_:02d}:{m:02d}:{s:02d}"
        p.fillRect(QRect(0, 0, min(w, 200), lh), color)
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        p.setFont(font)
        p.setPen(Qt.white)
        p.drawText(QRect(8, 0, min(w, 200) - 8, lh), Qt.AlignVCenter | Qt.AlignLeft, label)
