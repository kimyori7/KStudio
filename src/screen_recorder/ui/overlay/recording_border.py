"""대상(전체/창) 영역 테두리 — 녹화 대기(녹색) / 녹화 중(빨강·주황)."""
from __future__ import annotations
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget

from ...capture.targets import CaptureTarget
from ..capture_exclude import exclude_from_capture


_COLOR_STANDBY_VIDEO = QColor("#2E7D32")
_COLOR_STANDBY_GIF = QColor("#0277BD")
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

    def _current_color(self):
        if self._state == "standby":
            return _COLOR_STANDBY_GIF if self.mode == "gif" else _COLOR_STANDBY_VIDEO
        if self.mode == "gif":
            return _COLOR_GIF
        return _COLOR_VIDEO

    def _use_dash(self) -> bool:
        return self._state == "recording" and self.mode == "gif"

    def paintEvent(self, _):
        p = QPainter(self)
        color = self._current_color()

        w, h = self.width(), self.height()
        bt = self.BORDER_THICKNESS
        lh = self.LABEL_HEIGHT
        ct = self.CORNER_THICKNESS
        cl = self.CORNER_LENGTH

        # 1) 전체 폭 상단 타이틀바
        p.fillRect(QRect(0, 0, w, lh), color)

        # 2) 좌/우/하단 메인 테두리 (모서리와 겹치지 않는 구간만)
        if self._use_dash():
            pen = QPen(color, bt)
            pen.setStyle(Qt.CustomDashLine)
            pen.setDashPattern([8, 2])
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            half = bt // 2
            if h - lh - 2 * cl > 0:
                p.drawLine(half, lh + cl, half, h - cl)
                p.drawLine(w - 1 - half, lh + cl, w - 1 - half, h - cl)
            if w - 2 * cl > 0:
                p.drawLine(cl, h - 1 - half, w - cl, h - 1 - half)
        else:
            if h - lh - 2 * cl > 0:
                p.fillRect(0, lh + cl, bt, h - lh - 2 * cl, color)
                p.fillRect(w - bt, lh + cl, bt, h - lh - 2 * cl, color)
            if w - 2 * cl > 0:
                p.fillRect(cl, h - bt, w - 2 * cl, bt, color)

        # 3) 네 귀퉁이 굵은 L자
        p.fillRect(0, lh, cl, ct, color)
        p.fillRect(0, lh, ct, cl, color)
        p.fillRect(w - cl, lh, cl, ct, color)
        p.fillRect(w - ct, lh, ct, cl, color)
        p.fillRect(0, h - ct, cl, ct, color)
        p.fillRect(0, h - cl, ct, cl, color)
        p.fillRect(w - cl, h - ct, cl, ct, color)
        p.fillRect(w - ct, h - cl, ct, cl, color)

        # 4) 라벨 텍스트
        if self._state == "standby":
            label = "◇ 대기 중"
        else:
            h_, rem = divmod(self._elapsed, 3600)
            m, s = divmod(rem, 60)
            prefix = "● REC" if self.mode == "video" else "◆ GIF"
            label = f"{prefix}  {h_:02d}:{m:02d}:{s:02d}"
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        p.setFont(font)
        p.setPen(Qt.white)
        p.drawText(QRect(10, 0, w - 20, lh), Qt.AlignVCenter | Qt.AlignLeft, label)

    def stop(self):
        self._tick_timer.stop()
        self._sec_timer.stop()
        self.close()
