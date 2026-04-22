"""메인 윈도우 셸: 상단 컨트롤바 + 좌측 사이드바 + 우측 패널 + 하단 상태바."""
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget

from screen_recorder.core.settings import AppSettings
from .control_bar import ControlBar
from .sidebar import Sidebar
from .status_bar import StatusBar


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

        self.control_bar = ControlBar()
        outer.addWidget(self.control_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        outer.addWidget(body, stretch=1)

        self.sidebar = Sidebar()
        self.sidebar.setFixedWidth(140)
        body_layout.addWidget(self.sidebar)

        self.panel_stack = QStackedWidget()
        body_layout.addWidget(self.panel_stack, stretch=1)

        self.status_bar = StatusBar()
        self.status_bar.setFixedHeight(28)
        outer.addWidget(self.status_bar)

        self.app_settings = AppSettings()
        self.panels: dict[str, QWidget] = {}

        from .panels.general_panel import GeneralPanel
        self.panels["general"] = GeneralPanel(self.app_settings.general)
        self.panel_stack.addWidget(self.panels["general"])

        from .panels.video_panel import VideoPanel
        self.panels["video"] = VideoPanel(self.app_settings.video)
        self.panel_stack.addWidget(self.panels["video"])

        from .panels.gif_panel import GifPanel
        self.panels["gif"] = GifPanel(self.app_settings.gif)
        self.panel_stack.addWidget(self.panels["gif"])

        self.sidebar.panel_selected.connect(self._switch_panel)

    def _switch_panel(self, key: str) -> None:
        if key in self.panels:
            self.panel_stack.setCurrentWidget(self.panels[key])
