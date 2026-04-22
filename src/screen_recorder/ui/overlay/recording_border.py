"""대상(전체/창) 영역 테두리 — 녹화 대기(녹색) / 녹화 중(빨강·주황)."""
from __future__ import annotations
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget

from ...capture.targets import CaptureTarget
from ..capture_exclude import exclude_from_capture


_COLOR_STANDBY = QColor("#2E7D32")
_COLOR_VIDEO = QColor("#E53935")
_COLOR_GIF = QColor("#FFB300")


class RecordingBorder(QWidget):
    """
    target.current_rect() 를 매 틱 따라가며 그 주변에 테두리 + 좌상단 라벨 표시.
    - 상태: standby (녹색) / recording (빨강 또는 주황 커스텀 점선)
    - 캡처에서 제외되도록 WDA_EXCLUDEFROMCAPTURE 적용
    """
    BORDER_THICKNESS = 4
    CORNER_THICKNESS = 8
    CORNER_LENGTH = 22
    LABEL_HEIGHT = 26

    def __init__(self, target: CaptureTarget, mode: str = "video"):
        super().__init__()
        self.target = target
        self.mode = mode
        self._state = "standby"
        self._elapsed = 0

        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(500)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()

        self._sec_timer = QTimer(self)
        self._sec_timer.setInterval(1000)
        self._sec_timer.timeout.connect(self._sec)

        self._excluded = False

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.update()

    def start_recording(self) -> None:
        self._state = "recording"
        self._elapsed = 0
        self._sec_timer.start()
        self.update()

    def stop_recording(self) -> None:
        self._state = "standby"
        self._sec_timer.stop()
        self._elapsed = 0
        self.update()

    def _sec(self):
        self._elapsed += 1
        self.update()

    def _tick(self):
        rect = self.target.current_rect()
        if rect is None:
            self.hide()
            return
        t = self.BORDER_THICKNESS
        self.setGeometry(
            rect.x - t,
            rect.y - t - self.LABEL_HEIGHT,
            rect.w + 2 * t,
            rect.h + 2 * t + self.LABEL_HEIGHT,
        )
        self.show()
        if not self._excluded:
            self._excluded = exclude_from_capture(self)

    def _current_color_and_dash(self):
        if self._state == "standby":
            return _COLOR_STANDBY, None
        if self.mode == "gif":
            return _COLOR_GIF, [8, 2]
        return _COLOR_VIDEO, None

    def paintEvent(self, _):
        p = QPainter(self)
        color, dash = self._current_color_and_dash()

        w, h = self.width(), self.height()
        bt = self.BORDER_THICKNESS
        lh = self.LABEL_HEIGHT

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

        # 모서리 굵은 L자
        corner_pen = QPen(color, self.CORNER_THICKNESS)
        corner_pen.setCapStyle(Qt.FlatCap)
        p.setPen(corner_pen)
        cl = self.CORNER_LENGTH
        t = self.CORNER_THICKNESS // 2
        rx0, ry0 = 0, lh
        rx1, ry1 = w - 1, h - 1
        p.drawLine(rx0 + t, ry0 + t, rx0 + t + cl, ry0 + t)
        p.drawLine(rx0 + t, ry0 + t, rx0 + t, ry0 + t + cl)
        p.drawLine(rx1 - t - cl, ry0 + t, rx1 - t, ry0 + t)
        p.drawLine(rx1 - t, ry0 + t, rx1 - t, ry0 + t + cl)
        p.drawLine(rx0 + t, ry1 - t - cl, rx0 + t, ry1 - t)
        p.drawLine(rx0 + t, ry1 - t, rx0 + t + cl, ry1 - t)
        p.drawLine(rx1 - t - cl, ry1 - t, rx1 - t, ry1 - t)
        p.drawLine(rx1 - t, ry1 - t - cl, rx1 - t, ry1 - t)

        # 라벨
        if self._state == "standby":
            label = "◇ 대기 중"
        else:
            h_, rem = divmod(self._elapsed, 3600)
            m, s = divmod(rem, 60)
            prefix = "● REC" if self.mode == "video" else "◆ GIF"
            label = f"{prefix} {h_:02d}:{m:02d}:{s:02d}"
        p.fillRect(QRect(0, 0, min(w, 180), lh), color)
        font = QFont(); font.setBold(True); font.setPointSize(10)
        p.setFont(font)
        p.setPen(Qt.white)
        p.drawText(QRect(8, 0, min(w, 180) - 8, lh), Qt.AlignVCenter | Qt.AlignLeft, label)

    def stop(self):
        self._tick_timer.stop()
        self._sec_timer.stop()
        self.close()
