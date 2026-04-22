"""메인 윈도우 셸: 상단 컨트롤바 + 좌측 사이드바 + 우측 패널 + 하단 상태바."""
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Screen Recorder")
        self.resize(800, 550)

        central = QWidget()
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.control_bar_holder = QWidget()
        outer.addWidget(self.control_bar_holder)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        outer.addWidget(body, stretch=1)

        self.sidebar_holder = QWidget()
        self.sidebar_holder.setFixedWidth(140)
        body_layout.addWidget(self.sidebar_holder)

        self.panel_stack = QStackedWidget()
        body_layout.addWidget(self.panel_stack, stretch=1)

        self.status_holder = QWidget()
        self.status_holder.setFixedHeight(28)
        outer.addWidget(self.status_holder)
