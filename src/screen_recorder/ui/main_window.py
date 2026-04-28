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

from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter, QToolBar, QFileDialog,
    QMessageBox, QApplication, QSystemTrayIcon, QInputDialog,
)

from screen_recorder.core.controller import RecorderController
from screen_recorder.core.settings import AppSettings
from screen_recorder.core.state import RecorderState
from screen_recorder.hotkey.manager import HotkeyManager
from screen_recorder.capture.targets import (
    FullScreenTarget, RegionTarget, WindowTarget, Rect,
)

from PySide6.QtGui import QImage

from .menu_bar import KStudioMenuBar
from .global_toolbar import GlobalToolbar
from .annotation_toolbar import AnnotationToolbar
from .tool_palette import ToolPalette
from .tab_area import TabArea
from .docks.library_panel import LibraryPanel
from .docks.record_status_panel import RecordStatusPanel
from .library_model import LibraryModel, EntryKind
from .mode_controller import ModeController, AppMode
from .preferences_dialog import PreferencesDialog
from .status_bar import StatusBar
from .tray import TrayController
from .capture_exclude import exclude_from_capture
from .app_icon import app_icon
from .overlay.recording_border import RecordingBorder
from .overlay.adjustable_region import AdjustableRegionBorder
from .overlay.mini_control import MiniControl
from screen_recorder.screenshot.controller import ScreenshotController
from screen_recorder.screenshot.capture import save_png
from screen_recorder.core.filename import build_filename, resolve_collision

from .edit_tab import EditTab
from .video_tab import VideoTab
from image_editor.tools.select import SelectTool
from image_editor.tools.rect import RectTool
from image_editor.tools.arrow import ArrowTool
from image_editor.tools.text import TextTool


_TOOL_MAP = {
    "select": SelectTool,
    "rect": RectTool,
    "arrow": ArrowTool,
    "text": TextTool,
}


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, ffmpeg_path: Path):
        super().__init__()
        self.setWindowTitle("KStudio")
        self.setWindowIcon(app_icon())
        # 일반 OS 창 프레임 사용 (frameless 해제 — 메뉴 바를 위해)
        self.setWindowFlags(Qt.Window)

        # 마지막 위치/크기 복원 (없으면 기본 1280×820)
        s = settings.screenshot
        if s.viewer_x >= 0 and s.viewer_y >= 0 and s.viewer_w > 0 and s.viewer_h > 0:
            self.setGeometry(s.viewer_x, s.viewer_y, s.viewer_w, s.viewer_h)
        else:
            self.resize(1280, 820)

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
        self.library_panel = LibraryPanel(self.library_model, self.mode_controller)
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

        # 스크린샷 컨트롤러 (캡처 → captured 시그널 → LibraryModel + TabArea 라우팅)
        self._screenshot_ctrl = ScreenshotController(
            main_window=self,
            viewer_getter=lambda: None,
        )
        self._screenshot_ctrl.captured.connect(self._on_screenshot_captured)

        # ---------- 단축키 등록 ----------
        self._register_all_hotkeys()

        # ---------- 시그널 와이어링 ----------
        self._wire_signals()

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

    # ---------- 시그널 와이어링 ----------

    def _wire_signals(self) -> None:
        # 글로벌 툴바
        self.global_toolbar.record_clicked.connect(self._on_start_clicked)
        self.global_toolbar.pause_clicked.connect(self._on_pause_clicked)
        self.global_toolbar.stop_clicked.connect(self._on_stop_clicked)
        self.global_toolbar.capture_region_clicked.connect(self._on_shot_region_action)
        self.global_toolbar.capture_full_clicked.connect(self._on_shot_full_action)
        self.global_toolbar.target_changed.connect(self._on_target_changed)
        self.global_toolbar.monitor_changed.connect(self._on_fullscreen_monitor_changed)
        self.global_toolbar.mode_value_changed.connect(self._on_recording_mode_changed)
        self.global_toolbar.mode_clicked.connect(self._on_mode_button_clicked)
        self.global_toolbar.preferences_clicked.connect(self._open_preferences)
        self.global_toolbar.save_clicked.connect(self._save_current_screenshot)
        self.global_toolbar.copy_clicked.connect(self._copy_current_screenshot)

        # 메뉴
        self.menu_bar.save_requested.connect(self._save_current_screenshot)
        self.menu_bar.save_as_requested.connect(self._save_as_current_screenshot)
        self.menu_bar.open_save_folder_requested.connect(self._open_save_folder)
        self.menu_bar.quit_requested.connect(self.close)
        self.menu_bar.preferences_requested.connect(self._open_preferences)
        self.menu_bar.undo_requested.connect(self._on_undo)
        self.menu_bar.redo_requested.connect(self._on_redo)
        self.menu_bar.original_zoom_requested.connect(self._on_original)
        self.menu_bar.library_visibility_toggled.connect(self.library_panel.setVisible)
        self.menu_bar.record_status_visibility_toggled.connect(self.record_status_panel.setVisible)
        self.menu_bar.record_start_requested.connect(self._on_start_clicked)
        self.menu_bar.record_stop_requested.connect(self._on_stop_clicked)
        self.menu_bar.record_pause_requested.connect(self._on_pause_clicked)

        # 모드 / 탭 / 라이브러리
        self.mode_controller.mode_changed.connect(self._on_mode_changed)
        self.tab_area.snapshot_requested.connect(self._on_video_snapshot)
        self.tab_area.entry_closed.connect(self._on_tab_closed_by_user)
        self.tab_area.tab_added.connect(self._on_tab_added)
        self.tab_area.currentChanged.connect(self._on_active_tab_changed)
        self.library_panel.entry_open_requested.connect(self._open_entry)
        self.library_panel.entry_delete_requested.connect(self._on_library_delete)
        self.library_panel.entry_open_folder_requested.connect(self._on_library_open_folder)
        self.library_model.entry_renamed.connect(self._on_entry_renamed)

        # 영상 탭 프레임 → 스크린샷 단축키
        QShortcut(QKeySequence("Ctrl+Shift+P"), self,
                  activated=self._snapshot_current_video_frame)

        # 도구 팔레트
        self.tool_palette.tool_changed.connect(self._on_tool_changed)

        # 옵션바
        self.annotation_toolbar.color_changed.connect(self._on_color_changed)
        self.annotation_toolbar.thickness_changed.connect(self._on_thickness_changed)
        self.annotation_toolbar.undo_requested.connect(self._on_undo)
        self.annotation_toolbar.redo_requested.connect(self._on_redo)
        self.annotation_toolbar.original_requested.connect(self._on_original)
        self.annotation_toolbar.zoom_input_changed.connect(self._on_zoom_input)

        # 컨트롤러
        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.recording_finished.connect(self._on_finished)
        self.controller.error_occurred.connect(self._on_error)

        # 트레이
        self.tray.show_main.connect(self.showNormal)
        self.tray.quit_requested.connect(QApplication.instance().quit)
        self.tray.toggle_record.connect(self._on_hotkey_toggle)
        self.tray.screenshot_region.connect(self._on_shot_region_action)
        self.tray.screenshot_full.connect(self._on_shot_full_action)

    # ---------- 메인 창 ----------

    def showEvent(self, e):
        super().showEvent(e)
        if not self._self_excluded:
            self._self_excluded = exclude_from_capture(self)
        self._apply_dark_titlebar()

    def _apply_dark_titlebar(self) -> None:
        """Windows DWM 다크 타이틀바 활성화 (Win10 1809+ / Win11)."""
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = int(self.winId())
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # Win10 build 18985+
            value = ctypes.c_int(1)
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                ctypes.c_int(DWMWA_USE_IMMERSIVE_DARK_MODE),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if res != 0:
                # 구버전 Win10: attribute 19 시도
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd),
                    ctypes.c_int(19),
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )
        except Exception:
            pass

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
        self._border.stop_requested.connect(self._on_stop_clicked)
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

    # ---------- 스크린샷 / 녹화 결과 → LibraryModel + TabArea ----------

    def _on_screenshot_captured(self, image: QImage, label: str) -> None:
        display = self._build_screenshot_display_name(label)
        entry = self.library_model.add(
            EntryKind.SCREENSHOT,
            thumbnail=image,
            source_label=label,
            display_name=display,
        )
        self.tab_area.add_screenshot(image=image, source_label=label, entry_id=entry.id)
        self._restore_window_for_capture()

    def _build_screenshot_display_name(self, source_label: str) -> str:
        """파일명 규칙으로 디스크 저장 시 사용할 파일명을 미리 만든다 (캡처 즉시 라이브러리 표시용)."""
        from datetime import datetime
        return build_filename(
            pattern=self.app_settings.screenshot.filename_pattern,
            when=datetime.now(),
            mode="screenshot",
            target=source_label,
            extension=self.app_settings.screenshot.format,
        )

    def _restore_window_for_capture(self) -> None:
        if self.isHidden() or self.isMinimized():
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _estimate_duration_ms(self, path: Path) -> int:
        """간단한 추정 — 0 으로 시작하면 PlayerWidget.duration_changed 가 정확한 값을 채워준다."""
        return 0

    def _extract_first_frame(self, path: Path) -> QImage:
        """ffmpeg 으로 첫 프레임을 추출해 QImage 반환. 실패하면 회색 placeholder."""
        placeholder = QImage(64, 36, QImage.Format_ARGB32)
        placeholder.fill(0xFF222222)
        if not path.exists() or not self.ffmpeg_path.exists():
            return placeholder
        try:
            import subprocess
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp = Path(f.name)
            try:
                # 첫 프레임 1장 추출. -ss 0 + -frames:v 1. -y 로 덮어쓰기.
                # GIF 도 같은 명령으로 첫 프레임 추출됨.
                subprocess.run(
                    [str(self.ffmpeg_path), "-y", "-loglevel", "error",
                     "-i", str(path), "-frames:v", "1", str(tmp)],
                    check=True, capture_output=True, timeout=10,
                )
                img = QImage(str(tmp))
                if not img.isNull():
                    return img
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            logging.getLogger(__name__).warning("first-frame extract failed: %s", e)
        return placeholder

    def _open_entry(self, entry_id: int) -> None:
        if self.tab_area.find_index_by_entry(entry_id) >= 0:
            self.tab_area.focus_entry(entry_id)
            return
        entry = self.library_model.get(entry_id)
        if entry is None:
            return
        if entry.kind is EntryKind.SCREENSHOT:
            self.tab_area.add_screenshot(
                image=entry.thumbnail, source_label=entry.source_label, entry_id=entry.id
            )
        else:
            if entry.path is None:
                return
            self.tab_area.add_video(
                path=entry.path, source_label=entry.source_label,
                duration_ms=entry.duration_ms, entry_id=entry.id,
            )

    def _on_mode_changed(self, mode: AppMode) -> None:
        self.global_toolbar.set_mode(mode)
        is_image = (mode is AppMode.IMAGE)
        self.tool_palette.setVisible(is_image)
        self.annotation_toolbar.setVisible(is_image)

    def _on_mode_button_clicked(self, mode: AppMode) -> None:
        """사용자가 모드 토글 버튼을 직접 클릭 — 그 모드의 가장 최근 탭으로 점프."""
        target_kind = EntryKind.VIDEO if mode is AppMode.VIDEO else EntryKind.SCREENSHOT
        entries = self.library_model.entries(kind=target_kind)
        if not entries:
            self.mode_controller.set_mode(mode)
            return
        self._open_entry(entries[0].id)

    def _on_tab_closed_by_user(self, entry_id: int) -> None:
        # 라이브러리에는 그대로 남겨둔다 (탭만 닫힘).
        pass

    def _on_tab_added(self, widget, mode) -> None:
        """새 탭이 추가되면 그 탭의 시그널을 옵션바 등에 연결."""
        if isinstance(widget, EditTab):
            widget.canvas.zoom_changed.connect(self.annotation_toolbar.set_zoom_label)

    def _entry_for_current_tab(self):
        eid = self.tab_area.current_entry_id()
        if eid is None:
            return None
        return self.library_model.get(eid)

    # ---------- 라이브러리 컨텍스트 메뉴 ----------

    def _on_entry_renamed(self, entry_id: int, new_name: str) -> None:
        """라이브러리 인라인 편집으로 display_name 이 바뀜 — 디스크 path 가 있으면 같이 rename."""
        entry = self.library_model.get(entry_id)
        if entry is None or entry.path is None:
            return
        old_path = entry.path
        if not old_path.exists():
            return
        # 확장자 보존 — 사용자가 확장자 빼먹어도 자동 보전
        new_stem = Path(new_name).stem
        new_suffix = Path(new_name).suffix or old_path.suffix
        target = old_path.parent / f"{new_stem}{new_suffix}"
        if target == old_path or target.exists():
            return
        try:
            old_path.rename(target)
            entry.path = target
        except OSError as e:
            logging.getLogger(__name__).warning("rename failed: %s", e)

    def _on_library_delete(self, entry_id: int) -> None:
        entry = self.library_model.get(entry_id)
        if entry is None:
            return
        # 디스크 파일이 있으면 휴지통으로
        if entry.path is not None and entry.path.exists():
            try:
                from send2trash import send2trash
                send2trash(str(entry.path))
            except Exception as e:
                logging.getLogger(__name__).warning("send2trash failed: %s", e)
        # 열려 있는 탭도 같이 닫기
        idx = self.tab_area.find_index_by_entry(entry_id)
        if idx >= 0:
            self.tab_area._on_close_requested(idx)  # 내부 close — entry_closed 도 발화
        self.library_model.remove(entry_id)

    def _on_library_open_folder(self, entry_id: int) -> None:
        entry = self.library_model.get(entry_id)
        if entry is None:
            return
        if entry.path is not None and entry.path.exists():
            folder = entry.path.parent
        elif entry.kind is EntryKind.VIDEO:
            folder = Path(self.app_settings.general.output_dir or Path.home() / "Videos" / "KStudio")
        else:
            folder = Path(self.app_settings.screenshot.save_dir or Path.home() / "Pictures" / "KStudio")
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_video_snapshot(self, image: QImage, label_at: str) -> None:
        """영상 탭에서 '현재 프레임 → 스크린샷' 요청."""
        entry = self.library_model.add(
            EntryKind.SCREENSHOT, thumbnail=image, source_label=label_at
        )
        self.tab_area.add_screenshot(image=image, source_label=label_at, entry_id=entry.id)

    def _on_recording_mode_changed(self, mode_key: str) -> None:
        """녹화 모드 (영상/GIF) 변경 — 테두리·도크 라벨 즉시 반영."""
        self.app_settings.general.mode = mode_key
        self.record_status_panel.set_mode(mode_key)
        if self._border is not None and hasattr(self._border, "set_mode"):
            self._border.set_mode(mode_key)

    # ---------- 스크린샷 편집 액션 ----------

    def _current_screenshot_tab(self) -> EditTab | None:
        w = self.tab_area.currentWidget()
        return w if isinstance(w, EditTab) else None

    def _apply_tool_to_current_tab(self, tool_id: str) -> None:
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        color = QColor(self.app_settings.annotation.last_color)
        th = self.app_settings.annotation.last_thickness
        stack = tab.undo_stack
        if tool_id == "select":
            tab.canvas.set_tool(SelectTool())
        elif tool_id == "rect":
            tab.canvas.set_tool(RectTool(color, th, tab.canvas.shift_held, stack))
        elif tool_id == "arrow":
            tab.canvas.set_tool(ArrowTool(color, th, tab.canvas.shift_held, stack))
        elif tool_id == "text":
            tab.canvas.set_tool(TextTool(
                color, stack,
                on_commit=lambda: self.tool_palette.set_current_tool("select"),
            ))
        self.annotation_toolbar.set_undo_enabled(tab.undo_stack.canUndo())
        self.annotation_toolbar.set_redo_enabled(tab.undo_stack.canRedo())

    def _on_tool_changed(self, tool_id: str) -> None:
        self._apply_tool_to_current_tab(tool_id)

    def _on_color_changed(self, color) -> None:
        self.app_settings.annotation.last_color = color.name(QColor.HexRgb)
        self._apply_tool_to_current_tab(self.tool_palette.current_tool())

    def _on_thickness_changed(self, step: int) -> None:
        self.app_settings.annotation.last_thickness = step
        self._apply_tool_to_current_tab(self.tool_palette.current_tool())

    def _on_undo(self) -> None:
        tab = self._current_screenshot_tab()
        if tab:
            tab.undo_stack.undo()

    def _on_redo(self) -> None:
        tab = self._current_screenshot_tab()
        if tab:
            tab.undo_stack.redo()

    def _on_original(self) -> None:
        tab = self._current_screenshot_tab()
        if tab:
            tab.canvas.set_hundred_percent_mode()

    def _on_zoom_input(self, percent: int) -> None:
        tab = self._current_screenshot_tab()
        if tab:
            tab.canvas.set_zoom_factor(percent / 100.0)

    def _save_current_screenshot(self) -> None:
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        if tab.is_saved() and tab.undo_stack.isClean():
            return
        if tab.is_saved():
            path = tab.saved_path()
        else:
            save_dir = self.app_settings.screenshot.save_dir or str(Path.home() / "Pictures" / "KStudio")
            Path(save_dir).mkdir(parents=True, exist_ok=True)
            # 라이브러리 entry 의 display_name 이 있으면 그걸 우선 사용 (사용자가 변경했을 수 있음)
            entry = self._entry_for_current_tab()
            if entry is not None and entry.display_name:
                base = entry.display_name
            else:
                from datetime import datetime
                base = build_filename(
                    pattern=self.app_settings.screenshot.filename_pattern,
                    when=datetime.now(),
                    mode="screenshot",
                    target=tab.source_label(),
                    extension=self.app_settings.screenshot.format,
                )
            path = resolve_collision(Path(save_dir) / base)
        save_png(tab.image(), path)
        tab.mark_saved(path)
        # 라이브러리 entry 의 path 도 갱신
        entry = self._entry_for_current_tab()
        if entry is not None:
            entry.path = path
            self.library_model.rename(entry.id, path.name)

    def _save_as_current_screenshot(self) -> None:
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        suggested = (
            tab.saved_path()
            or Path(self.app_settings.screenshot.save_dir or Path.home() / "Pictures" / "KStudio") / "screenshot.png"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "다른 이름으로 저장", str(suggested), "PNG (*.png)"
        )
        if not path:
            return
        save_png(tab.image(), Path(path))
        tab.mark_saved(Path(path))

    def _copy_current_screenshot(self) -> None:
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        QApplication.clipboard().setImage(tab.image())

    def _open_save_folder(self) -> None:
        save_dir = self.app_settings.screenshot.save_dir or str(Path.home() / "Pictures" / "KStudio")
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(save_dir))

    def _open_preferences(self) -> None:
        dialog = PreferencesDialog(self.app_settings)
        dialog.exec()
        # 단축키가 바뀌었을 수 있으므로 재등록
        self._reregister_hotkey()

    # ---------- 탭 전환 시 옵션바·도구 동기화 ----------

    def _on_active_tab_changed(self) -> None:
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        self.annotation_toolbar.set_current_color(QColor(self.app_settings.annotation.last_color))
        self.annotation_toolbar.set_current_thickness_step(self.app_settings.annotation.last_thickness)
        self.annotation_toolbar.set_zoom_label(tab.canvas.current_zoom())

    # ---------- 영상 탭 단축키 ----------

    def _snapshot_current_video_frame(self) -> None:
        w = self.tab_area.currentWidget()
        if isinstance(w, VideoTab):
            w._on_snapshot()

    # ---------- 캡처 액션 ----------

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
        p = Path(path)
        duration_ms = self._estimate_duration_ms(p)
        thumb = self._extract_first_frame(p)
        entry = self.library_model.add(
            EntryKind.VIDEO,
            thumbnail=thumb,
            source_label=self.global_toolbar.current_target(),
            display_name=p.name,        # 실제 저장된 파일명을 라이브러리에 그대로 표시
            path=p,
            duration_ms=duration_ms,
        )
        self.tab_area.add_video(
            path=p, source_label=entry.source_label,
            duration_ms=duration_ms, entry_id=entry.id,
        )
        self._restore_window_for_capture()
        self.tray.tray.showMessage("녹화 완료", str(p), QSystemTrayIcon.Information, 5000)

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
        # 메인 창 위치/크기 영속화 (app/main.py 의 종료 hook 이 settings.save 호출)
        g = self.geometry()
        self.app_settings.screenshot.viewer_x = g.x()
        self.app_settings.screenshot.viewer_y = g.y()
        self.app_settings.screenshot.viewer_w = g.width()
        self.app_settings.screenshot.viewer_h = g.height()
        self.hotkeys.unregister()
        self._hide_border()
        e.accept()
