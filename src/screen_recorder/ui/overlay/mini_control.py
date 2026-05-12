"""녹화 중 화면 우측 하단의 작은 컨트롤 패널."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel


class MiniControl(QWidget):
    stop_clicked = Signal()
    pause_clicked = Signal()
    close_requested = Signal()   # X 버튼 — 사용자가 이 창을 다시 안 보고 싶음

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

        # X — 이 mini 창을 영구히 끄기. 녹화 자체는 계속됨 (stop 과 구분).
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedWidth(24)
        self.close_btn.setToolTip("이 창 다시 안 보기 (환경설정 → 작은 컨트롤로 재활성화)")
        self.close_btn.clicked.connect(self.close_requested.emit)
        layout.addWidget(self.close_btn)

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
