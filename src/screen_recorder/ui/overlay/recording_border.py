"""녹화 중 테두리 표시. 캡처 영역 바깥쪽에 그려서 결과물에 들어가지 않도록."""
from __future__ import annotations
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget

from ...capture.targets import Rect, CaptureTarget


class RecordingBorder(QWidget):
    BORDER_THICKNESS = 3

    def __init__(self, target: CaptureTarget, mode: str):
        super().__init__()
        self.target = target
        self.mode = mode
        self._elapsed = 0

        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._sec_timer = QTimer(self)
        self._sec_timer.setInterval(1000)
        self._sec_timer.timeout.connect(self._sec)
        self._sec_timer.start()

    def _sec(self):
        self._elapsed += 1
        self.update()

    def _tick(self):
        rect = self.target.current_rect()
        if rect is None:
            self.hide()
            return
        t = self.BORDER_THICKNESS
        self.setGeometry(rect.x - t, rect.y - t - 24, rect.w + 2 * t, rect.h + 2 * t + 24)
        self.show()

    def paintEvent(self, _):
        p = QPainter(self)
        color = QColor("#E53935") if self.mode == "video" else QColor("#FFB300")
        style = Qt.SolidLine if self.mode == "video" else Qt.DashLine
        pen = QPen(color, self.BORDER_THICKNESS, style)
        p.setPen(pen)

        border = QRect(
            self.BORDER_THICKNESS // 2,
            24 + self.BORDER_THICKNESS // 2,
            self.width() - self.BORDER_THICKNESS,
            self.height() - 24 - self.BORDER_THICKNESS,
        )
        p.drawRect(border)

        h, rem = divmod(self._elapsed, 3600)
        m, s = divmod(rem, 60)
        label = ("● REC" if self.mode == "video" else "◆ GIF") + f" {h:02d}:{m:02d}:{s:02d}"
        font = QFont(); font.setBold(True); font.setPointSize(10)
        p.setFont(font)
        p.fillRect(QRect(0, 0, 140, 24), color)
        p.setPen(Qt.white)
        p.drawText(QRect(6, 0, 140, 24), Qt.AlignVCenter | Qt.AlignLeft, label)

    def stop(self):
        self._timer.stop()
        self._sec_timer.stop()
        self.close()
