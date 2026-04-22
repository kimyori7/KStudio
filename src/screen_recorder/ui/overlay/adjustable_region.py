"""사용자가 드래그/리사이즈로 조정하는 영역 테두리.

- 대기(standby): 녹색 실선 + 모서리 굵은 L자 + 라벨 ◇ 대기 중
- 영상 녹화: 빨강 실선 + 모서리 굵은 L자 + 라벨 ● REC hh:mm:ss
- GIF 녹화:  주황 "긴 선 + 짧은 간격" 점선 + 모서리 굵은 L자 + 라벨 ◆ GIF hh:mm:ss

대기 상태에서는 테두리/타이틀바 영역으로 이동·크기 조절 가능.
내부는 투명(클릭 통과)이라 아래 어플과 상호작용 가능.
녹화 상태에서는 전체 클릭 통과(움직임 봉인) + 화면 캡처 제외.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QRect, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QRegion
from PySide6.QtWidgets import QWidget, QPushButton


_COLOR_STANDBY = QColor("#2E7D32")
_COLOR_VIDEO = QColor("#E53935")
_COLOR_GIF = QColor("#FFB300")


class AdjustableRegionBorder(QWidget):
    rect_changed = Signal(int, int, int, int)  # x, y, w, h (geometry 변경)
    close_requested = Signal()                 # 타이틀바 X 버튼 클릭

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

        # 타이틀바 우상단 X 버튼 (전체화면으로 복귀)
        self.close_btn = QPushButton("✕", self)
        self.close_btn.setFixedSize(self.LABEL_HEIGHT, self.LABEL_HEIGHT)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("전체 화면으로 전환")
        self.close_btn.setStyleSheet(
            "QPushButton { background: transparent; color: white; border: none; "
            "font-weight: bold; font-size: 12pt; }"
            "QPushButton:hover { background-color: rgba(255, 255, 255, 60); }"
            "QPushButton:pressed { background-color: rgba(255, 255, 255, 100); }"
        )
        self.close_btn.clicked.connect(self.close_requested.emit)
        self._position_close_button()

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
        # X 버튼은 녹화 중 숨김 (클릭해도 녹화 중단되지 않도록)
        self.close_btn.hide()
        self.update()

    def stop_recording(self) -> None:
        self._state = "standby"
        self._sec_timer.stop()
        self._elapsed = 0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._update_mask()
        self.close_btn.show()
        self.update()

    def stop(self) -> None:
        """완전히 닫기."""
        self._sec_timer.stop()
        self.close()

    # ---------- 이벤트 ----------

    def showEvent(self, e):
        super().showEvent(e)
        self._update_mask()
        self._position_close_button()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_mask()
        self._position_close_button()

    def _position_close_button(self) -> None:
        size = self.LABEL_HEIGHT
        self.close_btn.move(self.width() - size, 0)
        self.close_btn.raise_()

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
        lh = self.LABEL_HEIGHT
        # 하단 코너 (리사이즈 유지)
        if x < cg and y > h - cg: return "sw"
        if x > w - cg and y > h - cg: return "se"
        # 타이틀바 영역은 항상 이동 (X 버튼 자리는 QPushButton이 먼저 잡음)
        if y < lh: return "move"
        # 좌우/하단 에지 리사이즈
        if x < eg: return "w"
        if x > w - eg: return "e"
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

    # ---------- 캡처 영역 ----------

    def current_capture_rect(self) -> tuple[int, int, int, int]:
        """
        실제 녹화 대상 사각형 (타이틀바/테두리 제외).
        = 화면상 위젯 위치 + 내부 여백을 감안한 '내부 영역' 절대 좌표.
        """
        bt = self.BORDER_THICKNESS
        lh = self.LABEL_HEIGHT
        return (
            self.x() + bt,
            self.y() + lh,
            max(1, self.width() - 2 * bt),
            max(1, self.height() - lh - bt),
        )

    # ---------- 그리기 ----------

    def _current_color(self) -> QColor:
        if self._state == "standby":
            return _COLOR_STANDBY
        if self.mode == "gif":
            return _COLOR_GIF
        return _COLOR_VIDEO

    def _use_dash(self) -> bool:
        """녹화 중 + GIF 일 때만 점선."""
        return self._state == "recording" and self.mode == "gif"

    def paintEvent(self, _):
        p = QPainter(self)
        color = self._current_color()
        w, h = self.width(), self.height()
        bt = self.BORDER_THICKNESS
        lh = self.LABEL_HEIGHT
        ct = self.CORNER_THICKNESS
        cl = self.CORNER_LENGTH

        # 1) 전체 폭 상단 타이틀바 (연속되어 보이도록 전체 가로 폭 채움)
        p.fillRect(QRect(0, 0, w, lh), color)

        # 2) 좌/우/하단 메인 테두리 — 모서리 L자와 겹치지 않는 '가운데 구간'만
        if self._use_dash():
            pen = QPen(color, bt)
            pen.setStyle(Qt.CustomDashLine)
            pen.setDashPattern([8, 2])
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            half = bt // 2
            if h - lh - 2 * cl > 0:
                p.drawLine(half, lh + cl, half, h - cl)                      # 좌
                p.drawLine(w - 1 - half, lh + cl, w - 1 - half, h - cl)      # 우
            if w - 2 * cl > 0:
                p.drawLine(cl, h - 1 - half, w - cl, h - 1 - half)           # 하
        else:
            # 실선은 fillRect로 (깔끔한 두께 보장)
            if h - lh - 2 * cl > 0:
                p.fillRect(0, lh + cl, bt, h - lh - 2 * cl, color)           # 좌
                p.fillRect(w - bt, lh + cl, bt, h - lh - 2 * cl, color)      # 우
            if w - 2 * cl > 0:
                p.fillRect(cl, h - bt, w - 2 * cl, bt, color)                # 하

        # 3) 네 귀퉁이 굵은 L자 (상시 실선, 내부 영역 기준)
        # 좌상
        p.fillRect(0, lh, cl, ct, color)              # 가로
        p.fillRect(0, lh, ct, cl, color)              # 세로
        # 우상
        p.fillRect(w - cl, lh, cl, ct, color)
        p.fillRect(w - ct, lh, ct, cl, color)
        # 좌하
        p.fillRect(0, h - ct, cl, ct, color)
        p.fillRect(0, h - cl, ct, cl, color)
        # 우하
        p.fillRect(w - cl, h - ct, cl, ct, color)
        p.fillRect(w - ct, h - cl, ct, cl, color)

        # 4) 타이틀바 라벨 텍스트
        inner_w = w - 2 * bt
        inner_h = h - lh - bt
        if self._state == "standby":
            label = f"◇ 대기 중  {inner_w}×{inner_h}"
        else:
            hh, rem = divmod(self._elapsed, 3600)
            mm, ss = divmod(rem, 60)
            prefix = "● REC" if self.mode == "video" else "◆ GIF"
            label = f"{prefix}  {hh:02d}:{mm:02d}:{ss:02d}   {inner_w}×{inner_h}"
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        p.setFont(font)
        p.setPen(Qt.white)
        p.drawText(QRect(10, 0, w - 20, lh), Qt.AlignVCenter | Qt.AlignLeft, label)
