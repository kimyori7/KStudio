"""메인 윈도우 셸 + 컨트롤러 와이어링."""
from __future__ import annotations
import logging
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
from .app_icon import app_icon
from .title_bar import CustomTitleBar
from .frameless_resize import FramelessResizer
from .overlay.recording_border import RecordingBorder
from .overlay.adjustable_region import AdjustableRegionBorder
from .overlay.mini_control import MiniControl
from .panels.general_panel import GeneralPanel
from .panels.screenshot_panel import ScreenshotPanel
from .panels.video_panel import VideoPanel
from .panels.hotkey_panel import HotkeyPanel
from .panels.preferences_panel import PreferencesPanel
from screen_recorder.screenshot.controller import ScreenshotController
from .screenshot_viewer import ScreenshotViewer


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, ffmpeg_path: Path):
        super().__init__()
        self.setWindowTitle("Screen Recorder")
        self.setWindowIcon(app_icon())
        self.resize(800, 550)

        # Frameless + 커스텀 타이틀바
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        # 자체 가장자리 리사이즈 핸들 (frameless 라 OS가 안 잡아줌)
        self._resizer = FramelessResizer(self, grip=6, min_w=640, min_h=420)

        self.app_settings = settings
        self.ffmpeg_path = ffmpeg_path

        # ---------- 레이아웃 ----------
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 커스텀 타이틀바
        self.title_bar = CustomTitleBar("Screen Recorder")
        self.title_bar.minimize_clicked.connect(self.showMinimized)
        self.title_bar.close_clicked.connect(self.close)
        outer.addWidget(self.title_bar)

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
            "screenshot": ScreenshotPanel(self.app_settings.screenshot),
            "video": VideoPanel(
                self.app_settings.video,
                self.app_settings.gif,
                self.app_settings.sound,
            ),
            "hotkey": HotkeyPanel(self.app_settings.hotkey),
            "preferences": PreferencesPanel(self.app_settings.preferences),
        }
        for panel in self.panels.values():
            self.panel_stack.addWidget(panel)
        self.sidebar.panel_selected.connect(self._switch_panel)

        # ---------- 컨트롤러 & 부수 모듈 ----------
        self.controller = RecorderController(self.app_settings, self.ffmpeg_path)
        self.hotkeys = HotkeyManager(host_widget=self)
        self.tray = TrayController(self)

        self._border: QWidget | None = None  # RecordingBorder 또는 AdjustableRegionBorder
        self._mini: MiniControl | None = None
        self._self_excluded = False

        # 스크린샷
        self._screenshot_viewer: ScreenshotViewer | None = None
        self._screenshot_ctrl = ScreenshotController(
            main_window=self,
            viewer_getter=lambda: self._screenshot_viewer,
        )
        self._screenshot_ctrl.captured.connect(self._on_screenshot_captured)

        # ---------- 단축키 등록 ----------
        self._register_all_hotkeys()

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

        self.control_bar.screenshot_clicked.connect(self._on_shot_region_action)
        self.tray.screenshot_region.connect(self._on_shot_region_action)
        self.tray.screenshot_full.connect(self._on_shot_full_action)

        # 모드(영상/GIF) 변경 시 현재 보이는 테두리의 색/점선 패턴 즉시 반영
        self.panels["general"].settings_changed.connect(self._on_general_changed)

        # 단축키 패널 편집 중에는 전역 훅 임시 해제
        hotkey_panel = self.panels["hotkey"]
        hotkey_panel.editing_started.connect(self._pause_hotkey)
        hotkey_panel.editing_finished.connect(self._resume_hotkey)
        hotkey_panel.settings_changed.connect(self._reregister_hotkey)

        # 마지막에 사용한 대상(전체화면/특정 창/지정 영역) 복원
        saved_target = self.app_settings.general.target
        if saved_target in ("fullscreen", "window", "region"):
            self.control_bar.set_target(saved_target)
            # window 모드는 매번 창 선택이 필요해서 자동 복원 안 함 (테두리도 띄울 수 없음)
            if saved_target == "region":
                self._show_region_border()

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
        # 다음 실행에서도 같은 대상이 선택되도록 저장
        self.app_settings.general.target = kind
        if kind == "region":
            self._show_region_border()
        else:
            self._hide_border()
            # 지정 영역 상태 텍스트가 남아있지 않도록 초기화
            if self.controller.state == RecorderState.IDLE:
                self.status_bar.state_label.setText("● 대기 중")
                self.status_bar.state_label.setStyleSheet("color: #666;")

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
        self._border.close_requested.connect(self._on_region_close_requested)
        self._border.show()
        exclude_from_capture(self._border)
        x, y, w, h = geom
        self.status_bar.state_label.setText(
            f"● 대기 중 (영역 {w}×{h} @ {x},{y})"
        )

    def _on_region_close_requested(self) -> None:
        """지정 영역 테두리의 X 버튼 클릭 → 전체화면 모드로 복귀."""
        self.control_bar.set_target("fullscreen")
        self._on_target_changed("fullscreen")

    def _on_region_moved(self, x: int, y: int, w: int, h: int) -> None:
        # 설정에 저장 (다음 실행에도 유지)
        g = self.app_settings.general
        g.region_x, g.region_y, g.region_w, g.region_h = x, y, w, h
        # 녹화 중이면 capture thread에 위치 변경 알림 (크기는 hit_test에서 잠금 처리됨)
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
        kind = self.control_bar.current_target()
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
        log = logging.getLogger(__name__)
        log.info(
            "Start recording: target=%s, mode=%s, audio=%s",
            self.control_bar.current_target(),
            self.app_settings.general.mode,
            self.app_settings.sound.system_audio_enabled,
        )
        try:
            self.controller.start_recording(target)
        except Exception as e:
            QMessageBox.warning(self, "녹화 시작 실패", str(e))
            return

        kind = self.control_bar.current_target()
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

        kind = self.control_bar.current_target()
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

    # ---------- 스크린샷 액션 ----------

    def _ensure_viewer(self) -> ScreenshotViewer:
        if self._screenshot_viewer is None:
            v = ScreenshotViewer(self.app_settings)
            v.closed.connect(self._on_viewer_closed)
            self._screenshot_viewer = v
        return self._screenshot_viewer

    def _on_viewer_closed(self) -> None:
        self._screenshot_viewer = None

    def _on_screenshot_captured(self, image, label: str):
        viewer = self._ensure_viewer()
        viewer.add_tab(image, source_label=label)

    def _on_shot_region_action(self) -> None:
        self._screenshot_ctrl.capture_region()

    def _on_shot_full_action(self) -> None:
        self._screenshot_ctrl.capture_full()

    def _on_hotkey_shot_region(self) -> None:
        # pynput 스레드에서 들어오므로 Qt main 스레드로 라우팅
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
        self.control_bar.set_recording(is_active)
        self.status_bar.set_recording(state == RecorderState.RECORDING)
        self.status_bar.set_paused(state == RecorderState.PAUSED)
        # 녹화/일시정지 중에는 모드(영상·GIF) 변경 잠금
        self.panels["general"].set_recording(is_active)

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
        if self._screenshot_viewer is not None:
            self._screenshot_viewer.close()
            self._screenshot_viewer = None
        e.accept()
