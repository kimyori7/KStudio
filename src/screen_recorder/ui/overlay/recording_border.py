"""대상 영역 테두리 — 대기(녹색) / 녹화(빨강·주황)."""
from __future__ import annotations
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget

from ...capture.targets import CaptureTarget
from ..capture_exclude import exclude_from_capture


_COLOR_STANDBY = QColor("#2E7D32")   # 녹색 — 녹화 대기
_COLOR_VIDEO = QColor("#E53935")     # 빨강 — 영상 녹화
_COLOR_GIF = QColor("#FFB300")       # 주황 — GIF 녹화


class RecordingBorder(QWidget):
    """
    대상 영역 둘레에 테두리 + 좌상단 라벨을 항상 위에 그림.
    - 상태: 'standby' (녹색 실선, 라벨 없음)
             'recording' (빨강 실선 또는 주황 점선 + 경과 시간 라벨)
    - 테두리는 캡처 영역 바깥에 그려지고, WDA_EXCLUDEFROMCAPTURE 로 제외되어
      녹화 결과에 들어가지 않음.
    """
    BORDER_THICKNESS = 3
    LABEL_HEIGHT = 24

    def __init__(self, target: CaptureTarget, mode: str = "video"):
        super().__init__()
        self.target = target
        self.mode = mode                 # "video" | "gif"
        self._state = "standby"          # "standby" | "recording"
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
        # 녹화 상태일 때만 start

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
        # show() 이후에 winId가 유효해짐 — 한 번만 적용
        if not self._excluded:
            self._excluded = exclude_from_capture(self)

    def _current_color_and_style(self) -> tuple[QColor, Qt.PenStyle]:
        if self._state == "standby":
            return _COLOR_STANDBY, Qt.SolidLine
        if self.mode == "gif":
            return _COLOR_GIF, Qt.DashLine
        return _COLOR_VIDEO, Qt.SolidLine

    def paintEvent(self, _):
        p = QPainter(self)
        color, style = self._current_color_and_style()
        pen = QPen(color, self.BORDER_THICKNESS, style)
        p.setPen(pen)

        border = QRect(
            self.BORDER_THICKNESS // 2,
            self.LABEL_HEIGHT + self.BORDER_THICKNESS // 2,
            self.width() - self.BORDER_THICKNESS,
            self.height() - self.LABEL_HEIGHT - self.BORDER_THICKNESS,
        )
        p.drawRect(border)

        # 라벨
        if self._state == "standby":
            label = "◇ 대기 중"
        else:
            h, rem = divmod(self._elapsed, 3600)
            m, s = divmod(rem, 60)
            prefix = "● REC" if self.mode == "video" else "◆ GIF"
            label = f"{prefix} {h:02d}:{m:02d}:{s:02d}"

        font = QFont(); font.setBold(True); font.setPointSize(10)
        p.setFont(font)
        p.fillRect(QRect(0, 0, 140, self.LABEL_HEIGHT), color)
        p.setPen(Qt.white)
        p.drawText(
            QRect(6, 0, 140, self.LABEL_HEIGHT),
            Qt.AlignVCenter | Qt.AlignLeft,
            label,
        )

    def stop(self):
        """완전히 닫기 (대기 상태에서 취소하거나 앱 종료 시)."""
        self._tick_timer.stop()
        self._sec_timer.stop()
        self.close()
