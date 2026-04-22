"""녹화 중 화면 우측 하단의 작은 컨트롤 패널."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel


class MiniControl(QWidget):
    stop_clicked = Signal()
    pause_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        self.elapsed = QLabel("00:00:00")
        layout.addWidget(self.elapsed)

        self.pause_btn = QPushButton("⏸")
        self.pause_btn.setFixedWidth(32)
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        layout.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setFixedWidth(32)
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self.stop_btn)

        self._secs = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def show_at_bottom_right(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        self.move(screen.right() - self.width() - 16, screen.bottom() - self.height() - 16)
        self.show()
        self._secs = 0
        self._timer.start()

    def _tick(self):
        self._secs += 1
        h, rem = divmod(self._secs, 3600)
        m, s = divmod(rem, 60)
        self.elapsed.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def stop(self):
        self._timer.stop()
        self.close()
