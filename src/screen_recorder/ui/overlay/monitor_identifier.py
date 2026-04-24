"""모니터 식별 오버레이 — 각 모니터 중앙에 큰 번호를 잠깐 띄움.

Windows 의 "디스플레이 설정 → 식별" 버튼과 같은 역할. 다중 모니터 환경에서
어느 쪽이 몇 번인지 시각적으로 알려주는 용도.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QColor, QFont, QScreen
from PySide6.QtWidgets import QWidget


_BG_SIZE = 280


class MonitorIdentifier(QWidget):
    def __init__(self, screen: QScreen, number: int):
        super().__init__()
        self._number = number

        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.Tool)  # 작업표시줄에 안 뜸
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        g = screen.geometry()
        self.resize(_BG_SIZE, _BG_SIZE)
        self.move(
            g.x() + (g.width() - _BG_SIZE) // 2,
            g.y() + (g.height() - _BG_SIZE) // 2,
        )

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # 둥근 사각 반투명 배경
        p.setBrush(QColor(20, 20, 20, 210))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect(), 28, 28)

        # 얇은 테두리 (강조)
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(255, 255, 255, 80))
        p.drawRoundedRect(
            QRect(1, 1, self.width() - 2, self.height() - 2), 27, 27
        )

        # 큰 번호
        p.setPen(QColor(255, 255, 255))
        font = QFont()
        font.setPointSize(120)
        font.setBold(True)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, str(self._number))
