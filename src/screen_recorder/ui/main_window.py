"""메인 윈도우 셸 + 컨트롤러 와이어링."""
from __future__ import annotations
from pathlib import Path
import pygetwindow as gw

from PySide6.QtCore import Qt, QEventLoop, Slot
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QMessageBox, QApplication, QSystemTrayIcon, QInputDialog,
)

from screen_recorder.core.controller import RecorderController
from screen_recorder.core.settings import AppSettings
from screen_recorder.core.state import RecorderState
from screen_recorder.hotkey.manager import HotkeyManager
from screen_recorder.capture.targets import (
    FullScreenTarget, RegionTarget, WindowTarget,
)

from .sidebar import Sidebar
from .control_bar import ControlBar
from .status_bar import StatusBar
from .tray import TrayController
from .overlay.region_selector import RegionSelector
from .overlay.recording_border import RecordingBorder
from .overlay.mini_control import MiniControl
from .panels.general_panel import GeneralPanel
from .panels.video_panel import VideoPanel
from .panels.gif_panel import GifPanel
from .panels.sound_panel import SoundPanel
from .panels.hotkey_panel import HotkeyPanel
from .panels.preferences_panel import PreferencesPanel


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, ffmpeg_path: Path):
        super().__init__()
        self.setWindowTitle("Screen Recorder")
        self.resize(800, 550)

        self.app_settings = settings
        self.ffmpeg_path = ffmpeg_path

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

        # Panels
        self.panels: dict[str, QWidget] = {
            "general": GeneralPanel(self.app_settings.general),
            "video": VideoPanel(self.app_settings.video),
            "gif": GifPanel(self.app_settings.gif),
            "sound": SoundPanel(self.app_settings.sound),
            "hotkey": HotkeyPanel(self.app_settings.hotkey),
            "preferences": PreferencesPanel(self.app_settings.preferences),
        }
        for panel in self.panels.values():
            self.panel_stack.addWidget(panel)

        self.sidebar.panel_selected.connect(self._switch_panel)

        # Controller + hotkey + tray
        self.controller = RecorderController(self.app_settings, self.ffmpeg_path)
        self.hotkeys = HotkeyManager()
        self.tray = TrayController(self)
        self._border: RecordingBorder | None = None
        self._mini: MiniControl | None = None

        # Register hotkey
        try:
            self.hotkeys.register(self.app_settings.hotkey.toggle_record, self._on_hotkey_toggle)
        except Exception:
            pass  # 단축키 등록 실패해도 앱은 떠야 함

        # Signals
        self.control_bar.start_clicked.connect(self._on_start_clicked)
        self.control_bar.stop_clicked.connect(self._on_stop_clicked)
        self.control_bar.pause_clicked.connect(self._on_pause_clicked)

        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.recording_finished.connect(self._on_finished)
        self.controller.error_occurred.connect(self._on_error)

        self.tray.show_main.connect(self.showNormal)
        self.tray.quit_requested.connect(QApplication.instance().quit)
        self.tray.toggle_record.connect(self._on_hotkey_toggle)

        self.panels["hotkey"].settings_changed.connect(self._reregister_hotkey)

    def _switch_panel(self, key: str) -> None:
        if key in self.panels:
            self.panel_stack.setCurrentWidget(self.panels[key])

    def _reregister_hotkey(self) -> None:
        try:
            self.hotkeys.register(self.app_settings.hotkey.toggle_record, self._on_hotkey_toggle)
        except Exception:
            pass

    def _build_target(self):
        kind = self.control_bar.target_combo.currentData()
        if kind == "fullscreen":
            return FullScreenTarget()
        if kind == "region":
            sel = RegionSelector()
            captured = {"rect": None}
            sel.region_selected.connect(lambda r: captured.update(rect=r))
            sel.show()
            loop = QEventLoop()
            sel.region_selected.connect(loop.quit)
            sel.cancelled.connect(loop.quit)
            loop.exec()
            if captured["rect"] is None:
                return None
            return RegionTarget(captured["rect"])
        if kind == "window":
            wins = [w for w in gw.getAllWindows() if w.title and w.visible]
            if not wins:
                return None
            title, ok = QInputDialog.getItem(
                self, "창 선택", "녹화할 창:",
                [w.title for w in wins], 0, False
            )
            if not ok:
                return None
            chosen = next((w for w in wins if w.title == title), None)
            return WindowTarget(chosen) if chosen else None
        return None

    def _on_start_clicked(self):
        target = self._build_target()
        if target is None:
            return
        try:
            self.controller.start_recording(target)
        except Exception as e:
            QMessageBox.warning(self, "녹화 시작 실패", str(e))
            return
        if self.app_settings.preferences.minimize_to_tray:
            self.hide()
        self._border = RecordingBorder(target, self.app_settings.general.mode)
        self._mini = MiniControl()
        self._mini.stop_clicked.connect(self._on_stop_clicked)
        self._mini.pause_clicked.connect(self._on_pause_clicked)
        self._mini.show_at_bottom_right()

    def _on_stop_clicked(self):
        self.controller.stop_recording()
        if self._border:
            self._border.stop()
            self._border = None
        if self._mini:
            self._mini.stop()
            self._mini = None
        self.showNormal()

    def _on_pause_clicked(self):
        if self.controller.state == RecorderState.RECORDING:
            self.controller.pause_recording()
        elif self.controller.state == RecorderState.PAUSED:
            self.controller.resume_recording()

    def _on_hotkey_toggle(self):
        # pynput callback runs on a different thread; dispatch to Qt main via invokeMethod
        from PySide6.QtCore import QMetaObject
        QMetaObject.invokeMethod(self, "_toggle_record_safe", Qt.QueuedConnection)

    @Slot()
    def _toggle_record_safe(self):
        if self.controller.state == RecorderState.IDLE:
            self._on_start_clicked()
        else:
            self._on_stop_clicked()

    def _on_state_changed(self, state):
        self.control_bar.set_recording(state != RecorderState.IDLE)
        self.status_bar.set_recording(state == RecorderState.RECORDING)
        self.status_bar.set_paused(state == RecorderState.PAUSED)

    def _on_finished(self, path: str):
        self.tray.tray.showMessage("녹화 완료", path, QSystemTrayIcon.Information, 5000)

    def _on_error(self, msg: str):
        QMessageBox.warning(self, "에러", msg)

    def closeEvent(self, e):
        if self.controller.state != RecorderState.IDLE:
            ret = QMessageBox.question(self, "종료", "녹화 중입니다. 정지하고 닫을까요?")
            if ret == QMessageBox.Yes:
                self._on_stop_clicked()
                self.hotkeys.unregister()
                e.accept()
            else:
                e.ignore()
        else:
            self.hotkeys.unregister()
            e.accept()
