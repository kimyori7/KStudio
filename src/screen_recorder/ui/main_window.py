"""메인 윈도우 셸 + 컨트롤러 와이어링."""
from __future__ import annotations
from pathlib import Path
import pygetwindow as gw

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QMessageBox, QApplication, QSystemTrayIcon, QInputDialog,
)

from screen_recorder.core.controller import RecorderController
from screen_recorder.core.settings import AppSettings
from screen_recorder.core.state import RecorderState
from screen_recorder.hotkey.manager import HotkeyManager
from screen_recorder.capture.targets import (
    FullScreenTarget, RegionTarget, WindowTarget, Rect,
)

from .sidebar import Sidebar
from .control_bar import ControlBar
from .status_bar import StatusBar
from .tray import TrayController
from .capture_exclude import exclude_from_capture
from .overlay.recording_border import RecordingBorder
from .overlay.adjustable_region import AdjustableRegionBorder
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

        # ---------- 레이아웃 ----------
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

        # ---------- 패널 ----------
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

        # ---------- 컨트롤러 & 부수 모듈 ----------
        self.controller = RecorderController(self.app_settings, self.ffmpeg_path)
        self.hotkeys = HotkeyManager()
        self.tray = TrayController(self)

        self._border: QWidget | None = None  # RecordingBorder 또는 AdjustableRegionBorder
        self._mini: MiniControl | None = None
        self._self_excluded = False

        # ---------- 단축키 등록 ----------
        try:
            self.hotkeys.register(self.app_settings.hotkey.toggle_record, self._on_hotkey_toggle)
        except Exception:
            pass

        # ---------- 시그널 연결 ----------
        self.control_bar.start_clicked.connect(self._on_start_clicked)
        self.control_bar.stop_clicked.connect(self._on_stop_clicked)
        self.control_bar.pause_clicked.connect(self._on_pause_clicked)
        self.control_bar.target_changed.connect(self._on_target_changed)

        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.recording_finished.connect(self._on_finished)
        self.controller.error_occurred.connect(self._on_error)

        self.tray.show_main.connect(self.showNormal)
        self.tray.quit_requested.connect(QApplication.instance().quit)
        self.tray.toggle_record.connect(self._on_hotkey_toggle)

        # 모드(영상/GIF) 변경 시 현재 보이는 테두리의 색/점선 패턴 즉시 반영
        self.panels["general"].settings_changed.connect(self._on_general_changed)

        # 단축키 패널 편집 중에는 전역 훅 임시 해제
        hotkey_panel = self.panels["hotkey"]
        hotkey_panel.editing_started.connect(self._pause_hotkey)
        hotkey_panel.editing_finished.connect(self._resume_hotkey)
        hotkey_panel.settings_changed.connect(self._reregister_hotkey)

    # ---------- 메인 창 ----------

    def showEvent(self, e):
        super().showEvent(e)
        if not self._self_excluded:
            self._self_excluded = exclude_from_capture(self)

    def _switch_panel(self, key: str) -> None:
        if key in self.panels:
            self.panel_stack.setCurrentWidget(self.panels[key])

    # ---------- 단축키 관리 ----------

    def _pause_hotkey(self) -> None:
        """단축키 입력 중에는 글로벌 훅 해제 (F9 눌러도 녹화 안 걸리게)."""
        try:
            self.hotkeys.unregister()
        except Exception:
            pass

    def _resume_hotkey(self) -> None:
        self._reregister_hotkey()

    def _reregister_hotkey(self) -> None:
        try:
            self.hotkeys.register(self.app_settings.hotkey.toggle_record, self._on_hotkey_toggle)
        except Exception:
            pass

    # ---------- 대상 / 테두리 ----------

    def _on_target_changed(self, kind: str) -> None:
        if kind == "region":
            self._show_region_border()
        else:
            self._hide_border()

    def _on_general_changed(self) -> None:
        # 모드(영상/GIF)가 바뀌었을 수 있으니 현재 테두리에 반영
        if self._border is not None and hasattr(self._border, "set_mode"):
            self._border.set_mode(self.app_settings.general.mode)

    def _default_region_geometry(self) -> tuple[int, int, int, int]:
        """화면 중앙에 1/4 크기 (가로/세로 각각 절반)."""
        screens = QGuiApplication.screens()
        if not screens:
            return (100, 100, 960, 540)
        g = screens[0].geometry()
        w = max(200, g.width() // 2)
        h = max(150, g.height() // 2)
        x = g.x() + (g.width() - w) // 2
        y = g.y() + (g.height() - h) // 2
        return (x, y, w, h)

    def _saved_or_default_region(self) -> tuple[int, int, int, int]:
        s = self.app_settings.general
        if s.region_x >= 0 and s.region_y >= 0 and s.region_w > 0 and s.region_h > 0:
            return (s.region_x, s.region_y, s.region_w, s.region_h)
        return self._default_region_geometry()

    def _show_region_border(self) -> None:
        self._hide_border()
        geom = self._saved_or_default_region()
        self._border = AdjustableRegionBorder(geom, mode=self.app_settings.general.mode)
        self._border.rect_changed.connect(self._on_region_moved)
        self._border.show()
        exclude_from_capture(self._border)
        x, y, w, h = geom
        self.status_bar.state_label.setText(
            f"● 대기 중 (영역 {w}×{h} @ {x},{y})"
        )

    def _on_region_moved(self, x: int, y: int, w: int, h: int) -> None:
        # 설정에 저장 (다음 실행에도 유지)
        g = self.app_settings.general
        g.region_x, g.region_y, g.region_w, g.region_h = x, y, w, h
        self.status_bar.state_label.setText(f"● 대기 중 (영역 {w}×{h} @ {x},{y})")

    def _hide_border(self) -> None:
        if self._border is not None:
            try:
                self._border.stop()
            except Exception:
                self._border.close()
            self._border = None

    # ---------- 시작 / 정지 ----------

    def _build_target(self):
        kind = self.control_bar.target_combo.currentData()
        if kind == "fullscreen":
            return FullScreenTarget()
        if kind == "region":
            # AdjustableRegionBorder가 있으면 내부(타이틀바/테두리 제외) 영역을 스냅샷
            if isinstance(self._border, AdjustableRegionBorder):
                x, y, w, h = self._border.current_capture_rect()
            else:
                wx, wy, ww, wh = self._saved_or_default_region()
                # 설정에 저장된 것도 '위젯' 좌표이므로 같은 규칙으로 보정
                bt = AdjustableRegionBorder.BORDER_THICKNESS
                lh = AdjustableRegionBorder.LABEL_HEIGHT
                x, y, w, h = wx + bt, wy + lh, max(1, ww - 2 * bt), max(1, wh - lh - bt)
            return RegionTarget(Rect(x, y, w, h))
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

    def _should_minimize_main(self) -> bool:
        """메인 창을 트레이로 숨길지 결정 — 미니 컨트롤이 꺼져있으면 항상 False."""
        prefs = self.app_settings.preferences
        return prefs.use_mini_control and prefs.minimize_to_tray

    def _on_start_clicked(self):
        target = self._build_target()
        if target is None:
            return
        try:
            self.controller.start_recording(target)
        except Exception as e:
            QMessageBox.warning(self, "녹화 시작 실패", str(e))
            return

        kind = self.control_bar.target_combo.currentData()
        # 영역 모드: 이미 있는 AdjustableRegionBorder 를 recording 으로 전환
        if kind == "region" and isinstance(self._border, AdjustableRegionBorder):
            self._border.set_mode(self.app_settings.general.mode)
            self._border.start_recording()
        else:
            # 전체/창 모드: 따라다니는 RecordingBorder 생성
            self._hide_border()
            self._border = RecordingBorder(target, mode=self.app_settings.general.mode)
            self._border.show()
            exclude_from_capture(self._border)
            self._border.start_recording()

        # 메인 창 트레이로 숨김 (미니 컨트롤 사용 + 트레이 옵션 ON 일 때만)
        if self._should_minimize_main():
            self.hide()

        # 미니 컨트롤 표시 (옵션)
        if self.app_settings.preferences.use_mini_control:
            self._mini = MiniControl()
            self._mini.stop_clicked.connect(self._on_stop_clicked)
            self._mini.pause_clicked.connect(self._on_pause_clicked)
            self._mini.show_at_bottom_right()
            exclude_from_capture(self._mini)

    def _on_stop_clicked(self):
        self.controller.stop_recording()
        if self._mini:
            self._mini.stop()
            self._mini = None

        kind = self.control_bar.target_combo.currentData()
        if kind == "region" and isinstance(self._border, AdjustableRegionBorder):
            # 영역 모드는 대기 상태로 복귀 (계속 표시)
            self._border.stop_recording()
        else:
            self._hide_border()

        if self._should_minimize_main():
            self.showNormal()

    def _on_pause_clicked(self):
        if self.controller.state == RecorderState.RECORDING:
            self.controller.pause_recording()
        elif self.controller.state == RecorderState.PAUSED:
            self.controller.resume_recording()

    def _on_hotkey_toggle(self):
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
            else:
                e.ignore()
                return
        self.hotkeys.unregister()
        self._hide_border()
        e.accept()
