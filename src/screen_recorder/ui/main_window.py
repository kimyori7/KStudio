"""메인 윈도우 셸 + 컨트롤러 와이어링 (포토샵 스타일).

레이아웃:
- 메뉴 바 (KStudioMenuBar)
- 글로벌 툴바 (GlobalToolbar) — 모드 토글 + 녹화 + 옵션 + 액션
- 옵션바 (AnnotationToolbar) — 색·두께·undo·줌
- 본체: ToolPalette | TabArea | (LibraryPanel + RecordStatusPanel)
- 상태바 (StatusBar)

기존 컨트롤러/단축키/트레이/녹화 흐름은 그대로 유지하고 UI 레이아웃과 위젯만 교체.
시그널 와이어링은 일부만 — 캡처/녹화 흐름은 Task 16, 도구/저장/복사/환경설정은 Task 17 에서 마무리.
"""
from __future__ import annotations
import logging
from pathlib import Path
import pygetwindow as gw

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter, QToolBar,
    QMessageBox, QApplication, QSystemTrayIcon, QInputDialog,
)

from screen_recorder.core.controller import RecorderController
from screen_recorder.core.settings import AppSettings
from screen_recorder.core.state import RecorderState
from screen_recorder.hotkey.manager import HotkeyManager
from screen_recorder.capture.targets import (
    FullScreenTarget, RegionTarget, WindowTarget, Rect,
)

from .menu_bar import KStudioMenuBar
from .global_toolbar import GlobalToolbar
from .annotation_toolbar import AnnotationToolbar
from .tool_palette import ToolPalette
from .tab_area import TabArea
from .docks.library_panel import LibraryPanel
from .docks.record_status_panel import RecordStatusPanel
from .library_model import LibraryModel
from .mode_controller import ModeController, AppMode
from .status_bar import StatusBar
from .tray import TrayController
from .capture_exclude import exclude_from_capture
from .app_icon import app_icon
from .overlay.recording_border import RecordingBorder
from .overlay.adjustable_region import AdjustableRegionBorder
from .overlay.mini_control import MiniControl
from screen_recorder.screenshot.controller import ScreenshotController
from .screenshot_viewer import ScreenshotViewer  # Task 18 에서 제거


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, ffmpeg_path: Path):
        super().__init__()
        self.setWindowTitle("KStudio")
        self.setWindowIcon(app_icon())
        self.resize(1280, 820)
        # 일반 OS 창 프레임 사용 (frameless 해제 — 메뉴 바를 위해)
        self.setWindowFlags(Qt.Window)

        self.app_settings = settings
        self.ffmpeg_path = ffmpeg_path

        # ---------- 모델 / 컨트롤러 멤버 ----------
        self.library_model = LibraryModel()
        self.mode_controller = ModeController()

        # ---------- 메뉴 바 ----------
        self.menu_bar = KStudioMenuBar()
        self.setMenuBar(self.menu_bar)

        # ---------- 글로벌 툴바 (QToolBar 래퍼에 위젯 삽입) ----------
        self.global_toolbar = GlobalToolbar()
        self._global_tb_host = QToolBar("글로벌", self)
        self._global_tb_host.setMovable(False)
        self._global_tb_host.addWidget(self.global_toolbar)
        self.addToolBar(self._global_tb_host)

        # ---------- 옵션바 (annotation toolbar) ----------
        self.annotation_toolbar = AnnotationToolbar(self)
        self.addToolBarBreak()
        self.addToolBar(self.annotation_toolbar)

        # ---------- 본체 ----------
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)

        self.tool_palette = ToolPalette()
        splitter.addWidget(self.tool_palette)

        self.tab_area = TabArea(self.mode_controller, self.app_settings.player)
        splitter.addWidget(self.tab_area)
        splitter.setStretchFactor(1, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.library_panel = LibraryPanel(self.library_model)
        self.record_status_panel = RecordStatusPanel()
        right_layout.addWidget(self.library_panel, stretch=1)
        right_layout.addWidget(self.record_status_panel)
        right.setFixedWidth(220)
        splitter.addWidget(right)

        outer.addWidget(splitter, stretch=1)

        # 상태바
        self.status_bar = StatusBar()
        self.status_bar.setFixedHeight(28)
        outer.addWidget(self.status_bar)

        # ---------- 컨트롤러 & 부수 모듈 ----------
        self.controller = RecorderController(self.app_settings, self.ffmpeg_path)
        self.hotkeys = HotkeyManager(host_widget=self)
        self.tray = TrayController(self)

        self._border: QWidget | None = None
        self._mini: MiniControl | None = None
        self._self_excluded = False

        # 스크린샷 (구버전 ScreenshotViewer 흐름 유지 — Task 16 에서 TabArea 로 이전)
        self._screenshot_viewer: ScreenshotViewer | None = None
        self._screenshot_ctrl = ScreenshotController(
            main_window=self,
            viewer_getter=lambda: self._screenshot_viewer,
        )
        self._screenshot_ctrl.captured.connect(self._on_screenshot_captured)

        # ---------- 단축키 등록 ----------
        self._register_all_hotkeys()

        # ---------- 녹화/대상 시그널 와이어링 ----------
        self.global_toolbar.record_clicked.connect(self._on_start_clicked)
        self.global_toolbar.stop_clicked.connect(self._on_stop_clicked)
        self.global_toolbar.pause_clicked.connect(self._on_pause_clicked)
        self.global_toolbar.target_changed.connect(self._on_target_changed)
        self.global_toolbar.monitor_changed.connect(self._on_fullscreen_monitor_changed)
        self.global_toolbar.mode_value_changed.connect(self._on_mode_value_changed)

        # 캡처 버튼 (Task 16 에서 캡처 흐름 본격 와이어링)
        self.global_toolbar.capture_region_clicked.connect(self._on_shot_region_action)
        self.global_toolbar.capture_full_clicked.connect(self._on_shot_full_action)

        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.recording_finished.connect(self._on_finished)
        self.controller.error_occurred.connect(self._on_error)

        self.tray.show_main.connect(self.showNormal)
        self.tray.quit_requested.connect(QApplication.instance().quit)
        self.tray.toggle_record.connect(self._on_hotkey_toggle)
        self.tray.screenshot_region.connect(self._on_shot_region_action)
        self.tray.screenshot_full.connect(self._on_shot_full_action)

        # 저장된 옵션 복원
        self.global_toolbar.set_monitor_index(
            self.app_settings.general.fullscreen_monitor_index
        )
        self.global_toolbar.set_recording_mode(self.app_settings.general.mode)

        # 마지막 대상 복원
        saved_target = self.app_settings.general.target
        if saved_target in ("fullscreen", "window", "region"):
            self.global_toolbar.set_target(saved_target)
            if saved_target == "region":
                self._show_region_border()

        # 도크 상태바 초기 라벨
        self.record_status_panel.set_target(self.global_toolbar.current_target())
        self.record_status_panel.set_mode(self.app_settings.general.mode)

    # ---------- 메인 창 ----------

    def showEvent(self, e):
        super().showEvent(e)
        if not self._self_excluded:
            self._self_excluded = exclude_from_capture(self)

    # ---------- 단축키 관리 ----------

    def _pause_hotkey(self) -> None:
        try:
            self.hotkeys.unregister()
        except Exception:
            pass

    def _resume_hotkey(self) -> None:
        self._reregister_hotkey()

    def _reregister_hotkey(self) -> None:
        self._register_all_hotkeys()

    def _register_all_hotkeys(self) -> None:
        bindings = {
            self.app_settings.hotkey.toggle_record: self._on_hotkey_toggle,
            self.app_settings.hotkey.screenshot_region: self._on_hotkey_shot_region,
            self.app_settings.hotkey.screenshot_full: self._on_hotkey_shot_full,
        }
        try:
            self.hotkeys.set_bindings(bindings)
        except Exception:
            pass

    # ---------- 대상 / 테두리 ----------

    def _on_target_changed(self, kind: str) -> None:
        self.app_settings.general.target = kind
        self.record_status_panel.set_target(kind)
        if kind == "region":
            self._show_region_border()
        else:
            self._hide_border()
            if self.controller.state == RecorderState.IDLE:
                self.status_bar.state_label.setText("● 대기 중")
                self.status_bar.state_label.setStyleSheet("color: #666;")

    def _on_mode_value_changed(self, mode: str) -> None:
        """녹화 모드 (영상/GIF) 변경 — 테두리·도크 라벨 즉시 반영."""
        self.app_settings.general.mode = mode
        self.record_status_panel.set_mode(mode)
        if self._border is not None and hasattr(self._border, "set_mode"):
            self._border.set_mode(mode)

    def _on_fullscreen_monitor_changed(self, idx: int) -> None:
        self.app_settings.general.fullscreen_monitor_index = idx
        if (self.controller.state == RecorderState.IDLE
                and self.global_toolbar.current_target() == "fullscreen"):
            self.status_bar.state_label.setText(f"● 대기 중 (모니터 {idx + 1})")
            self.status_bar.state_label.setStyleSheet("color: #666;")

    def _default_region_geometry(self) -> tuple[int, int, int, int]:
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
        self._border.close_requested.connect(self._on_region_close_requested)
        self._border.show()
        exclude_from_capture(self._border)
        x, y, w, h = geom
        self.status_bar.state_label.setText(
            f"● 대기 중 (영역 {w}×{h} @ {x},{y})"
        )

    def _on_region_close_requested(self) -> None:
        self.global_toolbar.set_target("fullscreen")
        self._on_target_changed("fullscreen")

    def _on_region_moved(self, x: int, y: int, w: int, h: int) -> None:
        g = self.app_settings.general
        g.region_x, g.region_y, g.region_w, g.region_h = x, y, w, h
        if (self.controller.state != RecorderState.IDLE
                and isinstance(self._border, AdjustableRegionBorder)
                and self.controller._video_thread is not None):
            cap_x, cap_y, _w, _h = self._border.current_capture_rect()
            try:
                self.controller._video_thread.update_origin(cap_x, cap_y)
            except Exception:
                pass
        if self.controller.state == RecorderState.IDLE:
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
        kind = self.global_toolbar.current_target()
        if kind == "fullscreen":
            return FullScreenTarget(self.global_toolbar.current_monitor_index())
        if kind == "region":
            if isinstance(self._border, AdjustableRegionBorder):
                x, y, w, h = self._border.current_capture_rect()
            else:
                wx, wy, ww, wh = self._saved_or_default_region()
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
        prefs = self.app_settings.preferences
        return prefs.use_mini_control and prefs.minimize_to_tray

    def _on_start_clicked(self):
        target = self._build_target()
        if target is None:
            return
        log = logging.getLogger(__name__)
        log.info(
            "Start recording: target=%s, mode=%s, audio=%s",
            self.global_toolbar.current_target(),
            self.app_settings.general.mode,
            self.app_settings.sound.system_audio_enabled,
        )
        try:
            self.controller.start_recording(target)
        except Exception as e:
            QMessageBox.warning(self, "녹화 시작 실패", str(e))
            return

        kind = self.global_toolbar.current_target()
        if kind == "region" and isinstance(self._border, AdjustableRegionBorder):
            self._border.set_mode(self.app_settings.general.mode)
            self._border.start_recording()
        else:
            self._hide_border()
            self._border = RecordingBorder(target, mode=self.app_settings.general.mode)
            self._border.show()
            exclude_from_capture(self._border)
            self._border.start_recording()

        if self._should_minimize_main():
            self.hide()

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

        kind = self.global_toolbar.current_target()
        if kind == "region" and isinstance(self._border, AdjustableRegionBorder):
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

    # ---------- 스크린샷 액션 (구버전 흐름 — Task 16 에서 TabArea 로 이전) ----------

    def _ensure_viewer(self) -> ScreenshotViewer:
        if self._screenshot_viewer is None:
            v = ScreenshotViewer(self.app_settings)
            v.closed.connect(self._on_viewer_closed)
            self._screenshot_viewer = v
        return self._screenshot_viewer

    def _on_viewer_closed(self) -> None:
        self._screenshot_viewer = None

    def _on_screenshot_captured(self, image, label: str):
        # Task 16 에서 LibraryModel + TabArea.add_screenshot 흐름으로 교체
        viewer = self._ensure_viewer()
        viewer.add_tab(image, source_label=label)

    def _on_shot_region_action(self) -> None:
        self._screenshot_ctrl.capture_region()

    def _on_shot_full_action(self) -> None:
        self._screenshot_ctrl.capture_full()

    def _on_hotkey_shot_region(self) -> None:
        from PySide6.QtCore import QMetaObject
        QMetaObject.invokeMethod(self, "_shot_region_safe", Qt.QueuedConnection)

    def _on_hotkey_shot_full(self) -> None:
        from PySide6.QtCore import QMetaObject
        QMetaObject.invokeMethod(self, "_shot_full_safe", Qt.QueuedConnection)

    @Slot()
    def _shot_region_safe(self):
        self._on_shot_region_action()

    @Slot()
    def _shot_full_safe(self):
        self._on_shot_full_action()

    def _on_state_changed(self, state):
        is_active = state != RecorderState.IDLE
        self.global_toolbar.set_recording_state(state)
        self.record_status_panel.set_state(state)
        self.status_bar.set_recording(state == RecorderState.RECORDING)
        self.status_bar.set_paused(state == RecorderState.PAUSED)

    def _on_finished(self, path: str):
        # Task 16 에서 LibraryModel + TabArea.add_video 흐름으로 확장
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
        if self._screenshot_viewer is not None:
            self._screenshot_viewer.close()
            self._screenshot_viewer = None
        e.accept()
