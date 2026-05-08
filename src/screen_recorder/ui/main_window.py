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

from PySide6.QtCore import (
    Qt, QFileSystemWatcher, QMimeData, QRect, QSize, QTimer, QUrl, Slot,
)
from PySide6.QtGui import (
    QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QGuiApplication,
    QKeySequence, QShortcut,
)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QToolBar,
    QDockWidget, QFileDialog, QMessageBox, QApplication, QSystemTrayIcon,
    QInputDialog, QProgressDialog, QDialog,
)

from screen_recorder.core.controller import RecorderController
from screen_recorder.core.settings import (
    AppSettings, default_image_dir, default_video_dir, save as save_settings, settings_path,
)
from screen_recorder.core.state import RecorderState
from screen_recorder.hotkey.manager import HotkeyManager
from screen_recorder.capture.targets import (
    FullScreenTarget, RegionTarget, WindowTarget, Rect,
)

from PySide6.QtGui import QImage, QPainter

from image_editor.format import write_kstudio
from image_editor.layer_model import LayerStack
from image_editor.layers.annotation_layer import AnnotationLayer
from image_editor.layers.image_layer import ImageLayer
from image_editor.operations.background_removal import BackgroundRemovalCommand
from image_editor.operations.crop import CropCommand
from image_editor.operations.magic_wand import MagicWandCommand
from image_editor.operations.mask_paint import MaskPaintCommand
from image_editor.operations.raster_paint import RasterPaintCommand
from image_editor.tools.crop import CropTool
from image_editor.tools.magic_wand import MagicWandTool
from image_editor.tools.mask_brush import MaskBrushTool
from image_editor.tools.raster_brush import RasterBrushTool

from .menu_bar import KStudioMenuBar
from .global_toolbar import GlobalToolbar
from .annotation_toolbar import AnnotationToolbar
from .tool_palette import ToolPalette
from .tab_area import TabArea
from .docks.layers_panel import LayersPanel
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
from .panels.inspector_panel import InspectorPanel
from screen_recorder.encode.trim import TrimJob
from screen_recorder.encode.filmstrip import FilmstripJob
from image_editor.tools.select import SelectTool
from image_editor.tools.selection import SelectionTool
from image_editor.tools.rect import RectTool
from image_editor.tools.arrow import ArrowTool
from image_editor.tools.text import TextTool


_TOOL_MAP = {
    "select": SelectTool,
    "rect": RectTool,
    "arrow": ArrowTool,
    "text": TextTool,
}


from PySide6.QtCore import QEvent, QObject


class _DockCloseFilter(QObject):
    """dock 의 X 버튼 close 만 잡아 menu_check 를 false 로. setVisible(False) 는 안 잡힘."""
    def __init__(self, dock_action_map: dict) -> None:
        super().__init__()
        self._map = dock_action_map

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Close:
            action = self._map.get(obj)
            if action is not None:
                action.setChecked(False)
        return False  # 이벤트 자체는 통과 (dock 정상 close)


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, ffmpeg_path: Path):
        super().__init__()
        # 초기화 중에는 디스크 persist 를 막는다 — Qt 위젯이 setCurrentIndex /
        # set_target 같은 프로그램 호출에도 currentIndexChanged 등 일부 시그널을
        # 발화시켜 핸들러(_on_fullscreen_monitor_changed 등)가 _persist_settings 를
        # 호출함. 그러면 테스트가 임시로 설정한 save_dir(예: pytest tmp) 가
        # 사용자 실제 settings.json 에 기록돼 영구 오염됨. 사용자 의도 변경은
        # __init__ 종료 후에만 발생하므로 그때부터 persist 허용.
        self._initializing = True
        # 트림 잡 lifecycle 추적 — 한 번에 하나만 진행.
        self._active_trim_job: TrimJob | None = None
        self._active_trim_src_widget = None
        self._active_trim_src_path: Path | None = None
        self._active_trim_dst_path: Path | None = None
        # 필름스트립 잡 보관 — entry_id 단위, 동시 다발적 추출 가능 (서로 독립).
        self._filmstrip_jobs: dict[int, FilmstripJob] = {}
        self.setWindowTitle("KStudio")
        self.setWindowIcon(app_icon())
        # 일반 OS 창 프레임 사용 (frameless 해제 — 메뉴 바를 위해)
        self.setWindowFlags(Qt.Window)
        # 외부에서 파일을 드래그 앤 드롭하면 자동으로 열도록 허용.
        self.setAcceptDrops(True)

        # 마지막 위치/크기 복원 (없으면 기본 1280×820)
        s = settings.screenshot
        if s.viewer_x >= 0 and s.viewer_y >= 0 and s.viewer_w > 0 and s.viewer_h > 0:
            self.setGeometry(s.viewer_x, s.viewer_y, s.viewer_w, s.viewer_h)
        else:
            self.resize(1280, 820)
        # 창을 작게 만드는 것이 차단되지 않도록 최소 크기 명시 (캡처 후 lockup 방지).
        self.setMinimumSize(480, 320)

        self.app_settings = settings
        self.ffmpeg_path = ffmpeg_path

        # ---------- 모델 / 컨트롤러 멤버 ----------
        self.library_model = LibraryModel()
        self.mode_controller = ModeController()
        # 마술봉 / 마스크 브러시 / 래스터 브러시 라이브 파라미터 (옵션 툴바 슬라이더와 동기화)
        self._magic_wand_tolerance = 32
        self._mask_brush_size = 30
        self._mask_brush_mode = "erase"
        self._raster_brush_size = 20
        self._current_special_tool = None  # 활성 brush/wand/mask-brush 참조

        # ---------- 메뉴 바 ----------
        self.menu_bar = KStudioMenuBar()
        self.setMenuBar(self.menu_bar)

        # ---------- 글로벌 툴바 (QToolBar 래퍼에 위젯 삽입) ----------
        self.global_toolbar = GlobalToolbar()
        self._global_tb_host = QToolBar("글로벌", self)
        # objectName 은 QMainWindow.saveState/restoreState 가 toolbar/dock 을 식별하는
        # 키. 없으면 매 실행마다 "objectName not set" 경고 + 위치 복원 불가능.
        self._global_tb_host.setObjectName("GlobalToolBarHost")
        self._global_tb_host.setMovable(False)
        self._global_tb_host.addWidget(self.global_toolbar)
        self.addToolBar(self._global_tb_host)

        # ---------- 옵션바 (annotation toolbar) ----------
        self.annotation_toolbar = AnnotationToolbar(self)
        self.annotation_toolbar.setObjectName("AnnotationToolBar")
        self.addToolBarBreak()
        self.addToolBar(self.annotation_toolbar)

        # ---------- 본체 (QDockWidget 기반) ----------
        # 중앙: 도구 팔레트 + 탭 영역. 나머지 패널은 dock 으로 분리해 자유 배치.
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.setSpacing(0)
        self.tool_palette = ToolPalette()
        center_row.addWidget(self.tool_palette)
        self.tab_area = TabArea(self.mode_controller, self.app_settings.player,
                                  self.app_settings.player_hotkeys)
        center_row.addWidget(self.tab_area, stretch=1)
        outer.addLayout(center_row, stretch=1)

        # 상태바
        self.status_bar = StatusBar()
        self.status_bar.setFixedHeight(28)
        outer.addWidget(self.status_bar)

        # ---------- 도크들 (라이브러리 / 레이어 / 녹화상태) ----------
        # 사용자가 떼어내거나 좌·우로 옮기거나 부동(floating)으로 띄울 수 있다.
        # objectName 은 saveState/restoreState 에서 매칭에 쓰이므로 고정값.
        self.library_panel = LibraryPanel(self.library_model, self.mode_controller)
        self.library_dock = QDockWidget("라이브러리", self)
        self.library_dock.setObjectName("LibraryDock")
        self.library_dock.setWidget(self.library_panel)
        self.library_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.library_dock)

        self.layers_panel = LayersPanel(self._dummy_stack())
        self.layers_dock = QDockWidget("레이어", self)
        self.layers_dock.setObjectName("LayersDock")
        self.layers_dock.setWidget(self.layers_panel)
        self.layers_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.layers_dock)

        self.record_status_panel = RecordStatusPanel(
            video=self.app_settings.video,
            gif=self.app_settings.gif,
            sound=self.app_settings.sound,
        )
        self.record_status_panel.settings_changed.connect(self._persist_settings)
        self.record_status_dock = QDockWidget("녹화 상태", self)
        self.record_status_dock.setObjectName("RecordStatusDock")
        self.record_status_dock.setWidget(self.record_status_panel)
        self.record_status_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.record_status_dock)

        self.inspector_panel = InspectorPanel()
        # 효과별 인스펙터 폼 등록 (Stage 3+)
        from .video.inspectors.caption_inspector import CaptionInspector
        self.inspector_panel.register_inspector("caption", CaptionInspector)
        from .video.inspectors.cut_inspector import CutInspector            # NEW
        self.inspector_panel.register_inspector("cut", CutInspector)        # NEW
        from .video.inspectors.speed_inspector import SpeedInspector        # Stage 5
        self.inspector_panel.register_inspector("speed", SpeedInspector)    # Stage 5
        from .video.inspectors.zoom_inspector import ZoomInspector          # Stage 6
        self.inspector_panel.register_inspector("zoom", ZoomInspector)      # Stage 6
        from .video.inspectors.broll_inspector import BrollInspector        # Stage 7
        self.inspector_panel.register_inspector("broll", BrollInspector)    # Stage 7
        self.inspector_dock = QDockWidget("효과 인스펙터", self)
        self.inspector_dock.setObjectName("InspectorDock")
        self.inspector_dock.setWidget(self.inspector_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.inspector_dock)
        self.inspector_dock.hide()   # 기본 숨김
        # 인스펙터 효과 변경 → 현재 활성 VideoTab 에만 전달 (단일 연결).
        # per-tab 연결 방식은 탭 N 개 열면 N 번 발화해 비활성 탭 사이드카도 덮어쓰는
        # 데이터 무결성 버그를 일으킴 (Stage 2 에서 도입, Stage 3a 에서 최초 노출).
        self.inspector_panel.effect_changed.connect(self._on_inspector_effect_changed)
        # 인스펙터 내 삭제 버튼(Stage 5+) → 현재 활성 탭의 EditController.remove_effect.
        self.inspector_panel.effect_deleted.connect(self._on_inspector_effect_deleted)

        # 호환성: 기존 코드에서 _left_dock_container 참조 가능 — 더이상 의미 없으나 None 으로 둔다.
        self._left_dock_container = None

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

        # 라이브러리 Del 한 항목들 (Ctrl+Z 복원용). 가장 최근 삭제가 stack 의 끝.
        # 각 항목은 (LibraryEntry 의 핵심 메타) — entry id 는 새로 발급되므로 보관 X.
        # path / kind / source_label / display_name / origin / duration_ms / thumbnail.
        self._undelete_stack: list[dict] = []

        # ---------- 단축키 등록 ----------
        self._register_all_hotkeys()
        self._editor_shortcuts: list[QShortcut] = []
        # EditorShortcuts 가 차지하는 키들은 메뉴 QAction 의 단축키와 겹치므로
        # 메뉴 단축키를 비우고 QShortcut 으로 일원화한다 (EditorShortcuts = 단일 소스).
        self._clear_menu_shortcuts_owned_by_editor()
        self._register_editor_shortcuts()

        # ---------- 시그널 와이어링 ----------
        self._wire_signals()

        # 저장된 옵션 복원
        self.global_toolbar.set_monitor_index(
            self.app_settings.general.fullscreen_monitor_index
        )
        self.global_toolbar.set_recording_mode(self.app_settings.general.mode)
        # 인라인 단축키 표시 (영상=영역 녹화, 이미지=영역 스크린샷) — 모니터 옆.
        self.global_toolbar.set_inline_hotkey("toggle_record", self.app_settings.hotkey.toggle_record)
        self.global_toolbar.set_inline_hotkey("screenshot_region", self.app_settings.hotkey.screenshot_region)

        # 마지막 대상 복원
        saved_target = self.app_settings.general.target
        if saved_target in ("fullscreen", "window", "region"):
            self.global_toolbar.set_target(saved_target)
            if saved_target == "region":
                self._show_region_border()

        # 도크 상태바 초기 라벨
        self.record_status_panel.set_target(self.global_toolbar.current_target())
        self.record_status_panel.set_mode(self.app_settings.general.mode)

        # 초기 모드에 맞춰 좌측 패널 가시성 동기화 (영상 모드면 레이어 숨김 등)
        self._on_mode_changed(self.mode_controller.mode())
        # 저장된 마지막 색/두께를 옵션바에 즉시 반영 (앱 재시작 시 테두리 표시 동기화).
        self.annotation_toolbar.set_current_color(QColor(self.app_settings.annotation.last_color))
        self.annotation_toolbar.set_current_thickness_step(self.app_settings.annotation.last_thickness)

        # dock 레이아웃 복원 — 사용자가 직전 세션에 옮긴 위치/크기/floating 상태 그대로.
        self._restore_dock_state()

        # 저장 폴더 스캔 → 라이브러리에 기존 파일들을 미리 채움.
        # 이미지/영상 모두 포함, 모드 필터는 LibraryPanel 이 알아서 처리.
        self._populate_library_from_disk()

        # 외부에서 파일이 삭제/이동되면 라이브러리에서도 자동 제거.
        self._setup_library_disk_watcher()

        # 초기화 끝 — 이제부터 사용자 액션에 의한 persist 허용.
        self._initializing = False

        # 첫 실행 시 단축키 프리셋 다이얼로그 노출 (preset_name="" 일 때만).
        # 노출은 이벤트 루프 시작 후로 미뤄 메인 창이 먼저 보이도록 한다.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._maybe_show_hotkey_preset_dialog)

        # MCP HTTP 브리지 — 환경설정에서 토글된 경우만 시작. 토큰이 비어 있으면
        # 자동 생성해 settings 에 영속화 (다음 실행에도 같은 토큰 유지 — CLI 가
        # 매번 재등록 안 해도 됨).
        from screen_recorder.mcp.pending_requests import PendingRequestStore
        self._mcp_bridge = None
        self._mcp_dispatcher = None
        self._mcp_request_store = PendingRequestStore()   # async 도구 결과 보관
        if self.app_settings.mcp.enabled:
            self._start_mcp_bridge()

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
        self.global_toolbar.hotkey_changed.connect(self._on_inline_hotkey_changed)
        # 인라인 단축키 capture 중에는 글로벌 Win32 핫키 일시 해제.
        self.global_toolbar.hotkey_editing_started.connect(self._pause_hotkey)
        self.global_toolbar.hotkey_editing_finished.connect(self._resume_hotkey)
        # 드래그-저장 버튼 — 현재 활성 EditTab 의 이미지를 제공.
        self.global_toolbar.drag_save_btn.image_provider = self._current_image_for_drag
        self.global_toolbar.drag_save_btn.filename_provider = self._current_filename_for_drag
        # 누끼 (배경 제거) — QAction 으로 노출, 단축키와 동일 핸들러로 라우팅.
        ra = self.global_toolbar.find_action("remove_bg")
        if ra is not None:
            ra.triggered.connect(self._on_remove_background)
        # 영상 내보내기 — 글로벌 툴바 버튼 + 단축키.
        self.global_toolbar.export_video_requested.connect(self._on_export_video)
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+Shift+E"), self).activated.connect(self._on_export_video)

        # 메뉴
        self.menu_bar.new_requested.connect(self._on_file_new)
        self.menu_bar.open_requested.connect(self._on_file_open)
        self.menu_bar.save_requested.connect(self._on_file_save)
        self.menu_bar.save_as_requested.connect(self._on_file_save_as)
        self.menu_bar.export_requested.connect(self._on_export)
        self.menu_bar.export_video_requested.connect(self._on_export_video)
        self.menu_bar.open_save_folder_requested.connect(self._open_save_folder)
        self.menu_bar.quit_requested.connect(self.close)
        self.menu_bar.preferences_requested.connect(self._open_preferences)
        self.menu_bar.undo_requested.connect(self._on_undo)
        self.menu_bar.redo_requested.connect(self._on_redo)
        self.menu_bar.toggle_edit_mode_requested.connect(self._toggle_edit_mode_via_menu)
        self.menu_bar.open_sidecar_dir_requested.connect(self._open_sidecar_dir)
        self.menu_bar.background_remove_requested.connect(self._on_remove_background)
        self.menu_bar.image_scale_requested.connect(self._on_image_scale)
        self.menu_bar.original_zoom_requested.connect(self._on_original)
        # dock 토글 — 메뉴 체크 → dock 가시성 (단방향).
        # NOTE: 양방향 동기화는 BUG: restoreState() 가 dock 을 transient 하게 hide 하면
        # visibilityChanged 가 발화해 menu_check 가 False 로 떨어진다. 이후
        # _enforce_dock_visibility 가 menu_check (=False) 를 읽어 dock 을 계속 숨긴 채로
        # 둠. 양방향이 아니라 menu_check = single source of truth.
        self.menu_bar.library_visibility_toggled.connect(self.library_dock.setVisible)
        self.menu_bar.tool_palette_visibility_toggled.connect(self._on_tool_palette_visibility_toggled)
        self.menu_bar.layers_visibility_toggled.connect(self._on_layers_visibility_toggled)
        self.menu_bar.record_status_visibility_toggled.connect(self._on_record_status_visibility_toggled)
        # 사용자가 dock 의 X 버튼을 직접 눌러 닫는 경우만 menu_check 갱신.
        # closeEvent 는 user 액션에만 발화하고 setVisible(False) 에는 발화하지 않음.
        self._wire_dock_user_close()
        self.menu_bar.record_start_requested.connect(self._on_start_clicked)
        self.menu_bar.record_stop_requested.connect(self._on_stop_clicked)
        self.menu_bar.record_pause_requested.connect(self._on_pause_clicked)
        self.menu_bar.about_requested.connect(self._show_about)

        # 모드 / 탭 / 라이브러리
        self.mode_controller.mode_changed.connect(self._on_mode_changed)
        self.tab_area.snapshot_requested.connect(self._on_video_snapshot)
        self.tab_area.entry_closed.connect(self._on_tab_closed_by_user)
        self.tab_area.tab_added.connect(self._on_tab_added)
        self.tab_area.currentChanged.connect(self._on_active_tab_changed)
        self.tab_area.video_duration_resolved.connect(self._on_video_duration_resolved)
        self.library_panel.entry_open_requested.connect(self._open_entry)
        self.library_panel.entry_delete_requested.connect(self._on_library_delete)
        self.library_panel.entry_open_folder_requested.connect(self._on_library_open_folder)
        self.library_panel.entry_undelete_requested.connect(self._on_library_undelete)
        self.library_model.entry_renamed.connect(self._on_entry_renamed)

        # 영상 탭 프레임 → 스크린샷 단축키 (PlayerHotkeys 에서 동적으로 가져옴)
        self._snapshot_shortcut = QShortcut(self)
        self._snapshot_shortcut.setKey(
            QKeySequence(self.app_settings.player_hotkeys.snapshot or "Ctrl+Shift+P")
        )
        self._snapshot_shortcut.activated.connect(self._snapshot_current_video_frame)
        # Ctrl+C → selection 이 있으면 그 영역만, 아니면 전체 합성 이미지를 클립보드.
        QShortcut(QKeySequence("Ctrl+C"), self,
                  activated=self._copy_current_screenshot)
        # Ctrl+X → selection 영역 잘라내기 (클립보드 복사 후 ImageLayer 에서 지움).
        QShortcut(QKeySequence("Ctrl+X"), self,
                  activated=self._cut_current_selection)
        # Del 처리는 LayerCanvas.keyPressEvent → EditTab.delete_selection 으로 위임.
        # WindowShortcut 으로 등록하면 LayersPanel 의 Del 을 가로채므로 여기에 추가하지 않는다.
        # Ctrl+A → 전체 선택. 캔버스 전체 영역을 selection 으로 설정.
        QShortcut(QKeySequence("Ctrl+A"), self,
                  activated=self._on_select_all)
        # Ctrl+D → 선택 해제.
        QShortcut(QKeySequence("Ctrl+D"), self,
                  activated=self._on_deselect_all)

        # 도구 팔레트
        self.tool_palette.tool_changed.connect(self._on_tool_changed)
        self.tool_palette.action_triggered.connect(self._on_palette_action)

        # 옵션바
        self.annotation_toolbar.color_changed.connect(self._on_color_changed)
        self.annotation_toolbar.thickness_changed.connect(self._on_thickness_changed)
        self.annotation_toolbar.undo_requested.connect(self._on_undo)
        self.annotation_toolbar.redo_requested.connect(self._on_redo)
        self.annotation_toolbar.original_requested.connect(self._on_original)
        self.annotation_toolbar.zoom_input_changed.connect(self._on_zoom_input)
        # 컨텍스트 옵션 — 마술봉 / 마스크 브러시 / 래스터 브러시
        self.annotation_toolbar.tolerance_changed.connect(self._on_tolerance_changed)
        self.annotation_toolbar.brush_size_changed.connect(self._on_brush_size_changed)
        self.annotation_toolbar.brush_mode_changed.connect(self._on_brush_mode_changed)
        self.annotation_toolbar.raster_size_changed.connect(self._on_raster_size_changed)

        # 컨트롤러
        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.recording_finished.connect(self._on_finished)
        self.controller.error_occurred.connect(self._on_error)

        # 트레이
        self.tray.show_main.connect(self.showNormal)
        self.tray.quit_requested.connect(self._force_quit_app)
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
            # 토글 상태 먼저 반영 — set_bindings 안에서 fallback 결정에 사용.
            self.hotkeys.set_intercept_enabled(
                bool(self.app_settings.hotkey.intercept_system_keys)
            )
            self.hotkeys.set_bindings(bindings)
        except Exception:
            pass

    # ---------- 편집기 단축키 (EditorShortcuts) ----------
    def _clear_menu_shortcuts_owned_by_editor(self) -> None:
        """EditorShortcuts 가 관리하는 키와 겹치는 메뉴 QAction 단축키를 비운다.

        QAction.setShortcut + 동일 키의 QShortcut 이 같은 윈도우에 공존하면 Qt
        가 'Ambiguous shortcut overload' 경고를 내며 둘 다 발화하지 않는다.
        EditorShortcuts 가 단일 소스가 되도록 메뉴 쪽 단축키를 제거한다.
        (메뉴 항목 자체는 그대로 클릭 가능 — 단축키 표시만 사라진다.)
        """
        for act_name in (
            "open_action", "save_action", "save_as_action", "export_png_action",
            "background_remove_action", "original_action",
            "toggle_edit_mode_action",  # Ctrl+E — 영상 모드 Ctrl+E 는 VideoTab.keyPressEvent 가 처리
        ):
            a = getattr(self.menu_bar, act_name, None)
            if a is not None:
                a.setShortcut(QKeySequence())

    def _register_editor_shortcuts(self) -> None:
        """EditorShortcuts 설정값을 QShortcut 으로 등록 (재호출 시 기존 것 정리)."""
        for s in self._editor_shortcuts:
            s.setParent(None)
        self._editor_shortcuts.clear()
        es = self.app_settings.editor_shortcuts

        def _add(seq_str: str, slot) -> None:
            if not seq_str:
                return
            sc = QShortcut(QKeySequence(seq_str), self)
            sc.activated.connect(slot)
            self._editor_shortcuts.append(sc)

        # Note: select/rect/arrow/text 단축키는 ToolPalette 가 자체 QShortcut 으로
        # 보유하고 있으므로 MainWindow 에서 또 등록하면 'Ambiguous shortcut overload'
        # 가 발생한다. 여기서는 Crop 만 등록 (ToolPalette 에 없는 도구).
        _add(es.tool_crop,   lambda: self._activate_editor_tool("crop"))
        _add(es.op_background_removal, self._on_remove_background)
        _add(es.op_image_scale, self._on_image_scale)
        _add(es.file_save,    self._on_file_save)
        _add(es.file_save_as, self._on_file_save_as)
        _add(es.file_export_png, lambda: self._on_export("png"))
        _add(es.file_open,    self._on_file_open)
        _add(es.view_actual_size, self._on_view_actual_size)
        _add(es.view_fit,     self._on_view_fit)

    def _activate_editor_tool(self, name: str) -> None:
        """단축키로 도구 활성화 — 도구 팔레트 경로와 동일하게 처리."""
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        if name == "crop":
            # 새 크롭 시작 — 기존 selection(marching ants) 은 혼란스러우니 정리.
            tab.selection.clear()
            tool = CropTool()
            tool.commit_requested.connect(lambda r, t=tab: self._on_crop_committed(t, r))
            tool.cursor_requested.connect(
                lambda shape, t=tab: t.canvas.viewport().setCursor(Qt.CursorShape(shape))
            )
            tab.canvas.set_tool(tool)
            return
        # select / rect / arrow / text 는 도구 팔레트와 동일한 경로 사용.
        if name in ("select", "rect", "arrow", "text"):
            self.tool_palette.set_current_tool(name)
            self._apply_tool_to_current_tab(name)

    def _on_crop_committed(self, tab: EditTab, rect) -> None:
        cmd = CropCommand(tab.stack, rect)
        tab.undo_stack.push(cmd)
        # 크롭 후 캔버스 크기가 바뀌면 이전 CropTool 인스턴스의 overlay/handles 가 옛
        # 좌표에 남아 위치가 어긋나 보임. 캔버스의 현재 도구가 여전히 CropTool 이면
        # 새 인스턴스로 갈아 끼워 깨끗한 상태로 다시 활성 — 사용자가 곧바로 다시 크롭 가능.
        if isinstance(tab.canvas.current_tool(), CropTool):
            self._apply_tool_to_current_tab("crop")

    def _on_view_actual_size(self) -> None:
        tab = self._current_screenshot_tab()
        if tab is not None:
            tab.canvas.set_zoom_factor(1.0)

    def _on_view_fit(self) -> None:
        tab = self._current_screenshot_tab()
        if tab is not None:
            tab.canvas.fit_to_view()

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
        self._persist_settings()

    def _on_inline_hotkey_changed(self, key: str, sequence_text: str) -> None:
        """글로벌 툴바 인라인 단축키 편집 — 즉시 settings 반영 + 핫키 재등록 + 저장."""
        if not hasattr(self.app_settings.hotkey, key):
            return
        if getattr(self.app_settings.hotkey, key) == sequence_text:
            return
        setattr(self.app_settings.hotkey, key, sequence_text)
        self._reregister_hotkey()
        self._persist_settings()

    def _on_fullscreen_monitor_changed(self, idx: int) -> None:
        self.app_settings.general.fullscreen_monitor_index = idx
        if (self.controller.state == RecorderState.IDLE
                and self.global_toolbar.current_target() == "fullscreen"):
            self.status_bar.state_label.setText(f"● 대기 중 (모니터 {idx + 1})")
            self.status_bar.state_label.setStyleSheet("color: #666;")
        # 즉시 디스크에 저장 — aboutToQuit 만 의존하면 강제 종료/크래시 시 손실. 모니터
        # 선택은 자주 바뀌지 않고 JSON 쓰기는 ms 단위라 hot path 아님.
        self._persist_settings()

    def _persist_settings(self) -> None:
        """app_settings 를 즉시 디스크에 저장. 자주 바뀌지 않는 설정에서만 호출.
        __init__ 중 (_initializing=True) 에는 no-op — Qt 가 위젯 초기 setChecked /
        setCurrentIndex 에 대해 자체 시그널을 발화시켜 핸들러가 의도치 않은 디스크
        쓰기를 일으키는 것을 막는다."""
        if getattr(self, "_initializing", False):
            return
        try:
            save_settings(self.app_settings, settings_path())
        except OSError as e:
            logging.getLogger(__name__).warning("settings save failed: %s", e)

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
        # 3-state 단축키: 어느 모드든 처음 누르면 영역 지정 UI 무장 →
        # 같은 키 다시 누르면 녹화 시작 → 또 누르면 녹화 종료.
        # 영역 picker 를 X 로 닫으면 _on_region_close_requested 가 fullscreen 으로
        # 되돌리므로 자연스럽게 "다음 단축키는 다시 무장" 상태로 들어간다.
        if self.controller.state != RecorderState.IDLE:
            self._on_stop_clicked()
            return
        armed = (self.global_toolbar.current_target() == "region"
                 and isinstance(self._border, AdjustableRegionBorder))
        if armed:
            self._on_start_clicked()
            return
        # 무장: 영역 모드로 전환 + AdjustableRegionBorder 표시.
        if self.global_toolbar.current_target() != "region":
            self.global_toolbar.set_target("region")
            self._on_target_changed("region")
        elif not isinstance(self._border, AdjustableRegionBorder):
            # 이미 region 인데 border 가 없는 예외 케이스 (수동 hide 등) 만 처리.
            self._show_region_border()

    # ---------- 스크린샷 / 녹화 결과 → LibraryModel + TabArea ----------

    def _on_screenshot_captured(self, image: QImage, label: str) -> None:
        display = self._build_screenshot_display_name(label)
        entry = self.library_model.add(
            EntryKind.SCREENSHOT,
            thumbnail=image,
            source_label=label,
            display_name=display,
        )
        self.tab_area.add_screenshot(image=image, source_label=label, entry_id=entry.id,
                                      display_name=display)
        self._restore_window_for_capture()
        # 새 캡처 후엔 항상 '선택' 도구로 리셋 (이전에 쓰던 brush/wand 등이 무한히 남는 문제 방지).
        self._reset_to_select_tool()

    def _reset_to_select_tool(self) -> None:
        """현재 활성 EditTab 의 도구를 select 로 리셋 — 캡처/녹화 직후 호출."""
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        self.tool_palette.set_current_tool("select")
        self._apply_tool_to_current_tab("select")
        self.annotation_toolbar.set_active_tool("select")

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
        # 캡처/녹화 완료 후 창을 항상 앞으로 올리고 포커스 부여.
        # RegionSelector 가 fullscreen 을 덮고 있다가 닫히면 KStudio 창이 뒤로 밀려
        # 있으므로, hidden/minimized 여부와 무관하게 raise+activate 한다.
        if self.isHidden() or self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        # dock 가시성 안전망 — restoreState/모드전환 등에서 부주의하게 닫힌 dock 복구.
        self._enforce_dock_visibility()

    def _wire_dock_user_close(self) -> None:
        """dock 의 X 버튼 클릭만 감지해 menu_check 를 갱신.

        eventFilter 로 QEvent.Close 를 감시. close 이벤트는 user 가 X 버튼 또는
        close() 명시 호출 시에만 발생하며, setVisible(False) 나 restoreState() 같은
        암묵적 hide 에는 발생하지 않는다.
        """
        self._dock_close_filter = _DockCloseFilter({
            self.library_dock: self.menu_bar.library_visible_action,
            self.layers_dock:  self.menu_bar.layers_visible_action,
            self.record_status_dock: self.menu_bar.status_visible_action,
        })
        for dock in (self.library_dock, self.layers_dock, self.record_status_dock):
            dock.installEventFilter(self._dock_close_filter)

    def _enforce_dock_visibility(self) -> None:
        """메뉴 체크 상태 + 모드 기준으로 dock 가시성을 강제 복구.

        Qt 의 minimize/restore, restoreState, mode 전환 등에서 dock 이 의도치 않게
        숨겨지는 경우의 안전망. 사용자가 명시적으로 끈 dock 은 메뉴 체크가 false 라
        그대로 hidden 유지된다.
        - library: 모드 무관 (메뉴 체크만)
        - layers: 이미지 모드 전용 (영상 모드면 자동 숨김)
        - record_status: 영상 모드 전용 (이미지 모드면 자동 숨김)
        """
        self.library_dock.setVisible(self.menu_bar.library_visible_action.isChecked())
        self.layers_dock.setVisible(self._layers_panel_visible_state())
        self.record_status_dock.setVisible(self._record_status_visible_state())

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
            import sys
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp = Path(f.name)
            # Windows: CREATE_NO_WINDOW 로 콘솔 깜박임 방지.
            no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            try:
                # 첫 프레임 1장 추출. -ss 0 + -frames:v 1. -y 로 덮어쓰기.
                # GIF 도 같은 명령으로 첫 프레임 추출됨.
                subprocess.run(
                    [str(self.ffmpeg_path), "-y", "-loglevel", "error",
                     "-i", str(path), "-frames:v", "1", str(tmp)],
                    check=True, capture_output=True, timeout=10,
                    creationflags=no_window,
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
        # display_name 이 비어 있으면 path.name 또는 source_label 로 폴백 — 어느 경우든
        # 사용자가 보는 라이브러리 항목 이름과 탭 라벨이 같도록 우선순위 명시.
        display_name = entry.display_name
        if not display_name:
            if entry.path is not None:
                display_name = entry.path.name
            else:
                display_name = entry.source_label
        if entry.kind is EntryKind.SCREENSHOT:
            # path 가 있으면 디스크에서 로드 (origin="opened" 또는 저장된 캡처)
            # — 라이브러리의 thumbnail 은 다운스케일 본일 수 있으므로 원본을 우선.
            if entry.path is not None and entry.path.exists():
                try:
                    tab = EditTab.from_file(entry.path)
                except (ValueError, OSError) as e:
                    QMessageBox.warning(self, "열기 실패", str(e))
                    return
                self.tab_area.add_image_tab(
                    tab, entry_id=entry.id, display_name=display_name
                )
            else:
                self.tab_area.add_screenshot(
                    image=entry.thumbnail, source_label=entry.source_label, entry_id=entry.id,
                    display_name=display_name,
                )
        else:
            if entry.path is None:
                return
            self.tab_area.add_video(
                path=entry.path, source_label=entry.source_label,
                duration_ms=entry.duration_ms, entry_id=entry.id,
                display_name=display_name,
                thumbnail=entry.thumbnail,
            )

    def _on_mode_changed(self, mode: AppMode) -> None:
        # 모드 전환 직전 dock 레이아웃 저장 (이전 모드 기준).
        prev_mode = getattr(self, "_last_mode", None)
        if prev_mode is not None and prev_mode is not mode:
            self._save_dock_state_for_mode(prev_mode)
        self._last_mode = mode
        self.global_toolbar.set_mode(mode)
        is_image = (mode is AppMode.IMAGE)
        # ToolPalette: 이미지 모드 + 창 메뉴 체크 둘 다일 때만
        tp_checked = self.menu_bar.tool_palette_visible_action.isChecked()
        self.tool_palette.setVisible(is_image and tp_checked)
        self.annotation_toolbar.setVisible(is_image)
        # 새 모드의 dock 레이아웃 복원 — 영상↔이미지 전환 시 사용자가 모드별로 떼어둔
        # 패널 배치를 그대로 유지.
        self._restore_dock_state_for_mode(mode)
        # restoreState 후 dock 가시성을 메뉴 체크 기준으로 강제 — restoreState 가 visibility
        # 도 같이 복원해 사용자가 닫지 않은 dock 도 닫는 부작용 방지.
        self._enforce_dock_visibility()
        # 영상 모드면 레이어 패널 비활성화 (모드 무관 호출 — 안전망).
        self._apply_layers_panel_enabled_state()
        # 모드 전용 dock 의 메뉴 항목 enable/disable 갱신.
        self._apply_mode_aware_menu_enabled()

    def _on_mode_button_clicked(self, mode: AppMode) -> None:
        """사용자가 모드 토글 버튼을 직접 클릭 — 그 모드의 가장 최근 탭으로 점프.

        주의: 모드 전환은 _open_entry 의 부수효과(currentChanged → mode_controller)
        에 의존하면 안 된다. focus_entry 가 이미 current 인 탭이면 no-op 이라 모드 시그널이
        발화되지 않아 다른 UI 들이 갱신 안 됨. 항상 명시적으로 set_mode 를 호출.
        """
        self.mode_controller.set_mode(mode)
        target_kind = EntryKind.VIDEO if mode is AppMode.VIDEO else EntryKind.SCREENSHOT
        entries = self.library_model.entries(kind=target_kind)
        if entries:
            self._open_entry(entries[0].id)
        # 영상 모드면 추가로 한 번 더 포커스 — _open_entry 가 이미 current 인 탭에서
        # focus_entry 를 호출하면 currentChanged 가 발화 안 해 _focus_current_video_tab
        # 이 자동으로 안 돌 수 있다.
        if mode is AppMode.VIDEO:
            self._focus_current_video_tab()

    def _on_video_duration_resolved(self, entry_id: int, duration_ms: int) -> None:
        """영상 player 가 로드 후 실제 duration 을 알려주면 라이브러리 항목도 갱신.

        탭 라벨은 TabArea 가 자체적으로 갱신하지만, 라이브러리 항목의 duration suffix
        는 LibraryModel 의 entry.duration_ms 로 만들어지므로 여기서 모델을 업데이트하고
        패널에 텍스트 재렌더 신호를 보낸다.
        """
        entry = self.library_model.get(entry_id)
        if entry is None or duration_ms <= 0:
            return
        if entry.duration_ms == duration_ms:
            return
        entry.duration_ms = duration_ms
        # 라이브러리 패널이 텍스트를 다시 렌더하도록 entry_renamed 시그널 (display_name 변동 없이도 텍스트 재계산).
        try:
            self.library_model.entry_renamed.emit(entry_id, entry.display_name)
        except Exception:
            pass
        # 정확한 duration 이 확정된 시점에 필름스트립(트림 레인 배경) 추출 시작.
        self._start_filmstrip_extraction(entry_id)

    def _on_tab_closed_by_user(self, entry_id: int) -> None:
        # 라이브러리에는 그대로 남겨둔다 (탭만 닫힘).
        pass

    def _on_tab_added(self, widget, mode) -> None:
        """새 탭이 추가되면 그 탭의 시그널을 옵션바 등에 연결."""
        if isinstance(widget, EditTab):
            widget.canvas.zoom_changed.connect(self.annotation_toolbar.set_zoom_label)
        elif isinstance(widget, VideoTab):
            widget.trim_requested.connect(self._on_trim_requested)
            self._hookup_video_tab_inspector(widget)
            # 같은 영상 entry 가 이미 필름스트립을 들고 있으면 즉시 적용 (재오픈 캐시).
            entry_id = self.tab_area.entry_id_for_widget(widget)
            if entry_id is not None:
                entry = self.library_model.get(entry_id)
                if entry is not None and entry.filmstrip:
                    widget.timeline.trim_marker_lane.set_filmstrip(entry.filmstrip)
                # duration 이 이미 확정돼 있으면 추출 시작 (영상 라이브러리에서 다시 열기 등).
                if entry is not None and entry.duration_ms > 0 and not entry.filmstrip:
                    self._start_filmstrip_extraction(entry_id)

    def _entry_for_current_tab(self):
        eid = self.tab_area.current_entry_id()
        if eid is None:
            return None
        return self.library_model.get(eid)

    # ---------- 인스펙터 도크 hookup ----------

    def _hookup_video_tab_inspector(self, tab) -> None:
        """영상 탭의 편집 모드/효과 선택을 인스펙터 도크에 연결.

        effect_changed 는 _on_inspector_effect_changed 에서 현재 활성 탭에만 단일 라우팅.
        per-tab 연결을 하면 탭 N 개마다 누적돼 비활성 탭 사이드카를 덮어쓰는 버그 발생.
        """
        tab.edit_mode_toggled.connect(self.inspector_dock.setVisible)
        tab.effect_selected.connect(self.inspector_panel.set_effect)

    def _on_inspector_effect_changed(self, new_effect) -> None:
        """인스펙터에서 효과가 수정됐을 때 현재 활성 VideoTab 에만 적용.

        inspector_panel.effect_changed 는 단일 연결(__init__ 에서 한 번만). 탭 전환 후에도
        항상 *현재* 활성 탭에만 적용되므로 비활성 탭의 사이드카/히스토리를 오염시키지 않는다.
        """
        widget = self.tab_area.currentWidget()
        if not isinstance(widget, VideoTab):
            return
        widget.edit_controller().update_sidecar(
            self._patch_sidecar_effect(widget.sidecar(), new_effect)
        )

    def _on_inspector_effect_deleted(self, effect_id: str) -> None:
        """인스펙터에서 효과 삭제 버튼 클릭 시 현재 활성 VideoTab 의 사이드카에서 제거.

        effect_changed 와 같은 단일 라우팅 패턴 — 탭 전환 후에도 항상 활성 탭에만 적용.
        """
        widget = self.tab_area.currentWidget()
        if not isinstance(widget, VideoTab):
            return
        widget.edit_controller().remove_effect(effect_id)

    def _patch_sidecar_effect(self, sidecar, new_effect):
        """사이드카에서 같은 id 의 효과를 new_effect 로 교체한 새 Sidecar 반환."""
        import copy
        sc = copy.deepcopy(sidecar)
        for i, e in enumerate(sc.effects):
            if e.id == new_effect.id:
                sc.effects[i] = new_effect
                break
        return sc

    # ---------- 라이브러리 컨텍스트 메뉴 ----------

    def _on_entry_renamed(self, entry_id: int, new_name: str) -> None:
        """라이브러리 인라인 편집으로 display_name 이 바뀜 — 디스크 path 가 있으면 같이 rename.

        이름 충돌·OSError 시: 사용자에게 안내 후 display_name 을 디스크 파일 stem 으로
        롤백 (라이브러리 표시와 디스크 파일명이 어긋난 채 유지되지 않도록)."""
        # 탭 라벨도 새 이름으로 갱신 (이미지·영상 모두). 저장 상태 ● 와 영상 duration
        # 접미사는 TabArea 가 자체 보존.
        self.tab_area.update_tab_base(entry_id, new_name)
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
        if target == old_path:
            return
        if target.exists():
            QMessageBox.warning(
                self, "이름 바꾸기 실패",
                f"같은 이름의 파일이 이미 존재합니다:\n{target.name}",
            )
            # display_name 롤백 — 디스크 파일 stem 으로. rename 시그널이 다시 발화하지만
            # target == old_path 가 되어 즉시 return.
            self.library_model.rename(entry_id, old_path.stem)
            return
        try:
            old_path.rename(target)
            entry.path = target
        except OSError as e:
            logging.getLogger(__name__).warning("rename failed: %s", e)
            QMessageBox.warning(
                self, "이름 바꾸기 실패",
                f"파일 이름을 바꿀 수 없습니다:\n{e}",
            )
            self.library_model.rename(entry_id, old_path.stem)

    def _on_library_delete(self, entry_id: int) -> None:
        entry = self.library_model.get(entry_id)
        if entry is None:
            return
        # 라이브러리에서 먼저 제거 — 사용자에게 즉각적인 UI 피드백을 주기 위함.
        # send2trash 와 영상 탭 close 는 Windows 에서 수백 ms 걸릴 수 있는데, 그 동안
        # 라이브러리에 항목이 남아 있으면 "Del 안 먹은 듯" 한 인상을 줌.
        path = entry.path
        kind = entry.kind
        idx = self.tab_area.find_index_by_entry(entry_id)

        # 영상/GIF 파일은 QMediaPlayer / QMovie 가 핸들을 잡고 있어 그대로 send2trash
        # 를 호출하면 Windows 가 "다른 프로그램이 사용 중" (sharing violation) 으로 거부.
        # 탭 닫기 전에 release_file_handles() 로 두 백엔드의 핸들을 모두 명시 해제하고,
        # processEvents 로 deferred deletion · media-pipeline tear-down 을 한 번 굴린다.
        widget = self.tab_area.tab_widget_for_entry(entry_id)
        if isinstance(widget, VideoTab):
            try:
                widget.player.stop()
                widget.player.release_file_handles()
            except (RuntimeError, AttributeError):
                pass

        # Ctrl+Z 복원용 스냅샷 (id 는 보관 X — 다음 add 시 새로 발급).
        snapshot = {
            "kind": entry.kind,
            "thumbnail": entry.thumbnail,
            "source_label": entry.source_label,
            "display_name": entry.display_name,
            "path": path,
            "duration_ms": entry.duration_ms,
            "origin": entry.origin,
        }

        self.library_model.remove(entry_id)
        # 같이 열려 있던 탭 닫기 (영상이면 player 해제도 같이).
        if idx >= 0:
            self.tab_area._on_close_requested(idx)
        # deleteLater 가 큐에 들어간 상태 — Qt 가 실제로 위젯을 파괴하고 미디어 백엔드의
        # 파일 핸들을 닫도록 이벤트 루프를 짧게 풀어 준다. GIF (QMovie/QImageReader) 는
        # 단순 processEvents 만으론 QFile 이 안 닫히는 일이 있어, sendPostedEvents 로
        # DeferredDelete 만 명시 처리한 뒤 한 번 더 processEvents 로 마무리.
        from PySide6.QtCore import QCoreApplication, QEvent
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QApplication.processEvents()

        trashed_ok = True
        # 디스크 파일이 있으면 휴지통으로 — sharing violation (file in use) 은 100ms
        # 뒤 한 번 재시도. 썸네일 추출 ffmpeg 가 막 끝나는 타이밍 등에서 성공.
        if path is not None and path.exists():
            try:
                self._send_to_trash_with_retry(path)
            except Exception as e:
                trashed_ok = False
                logging.getLogger(__name__).warning(
                    "send2trash failed for %s (%s): %s", path, kind, e,
                )
                QMessageBox.warning(
                    self, "삭제 실패",
                    f"파일을 휴지통으로 보낼 수 없습니다.\n다른 프로그램이 사용 중이거나 권한이 없을 수 있습니다.\n\n{path}\n\n{e}",
                )

        # 휴지통으로 잘 들어갔거나 (혹은 path 가 없는 미저장 항목) 만 undelete stack 에 푸시.
        # 스택은 짧게(8) 유지 — 너무 많이 쌓이면 메모리/혼란.
        if trashed_ok:
            self._undelete_stack.append(snapshot)
            if len(self._undelete_stack) > 8:
                self._undelete_stack.pop(0)

    def _send_to_trash_with_retry(self, path: Path) -> None:
        """send2trash + 짧은 재시도. GIF 의 QMovie 핸들 / 썸네일 ffmpeg 등이 막 끝나는
        타이밍에 실패할 수 있어, 한 번 100ms 대기 후 재시도하면 대개 성공."""
        from send2trash import send2trash
        import time
        try:
            send2trash(str(path))
            return
        except OSError as e:
            # 0x80270027 (sharing violation), 0x80070020 등 — file in use 류만 재시도
            text = str(e).lower()
            if not ("0x80270027" in text or "0x80070020" in text or "사용" in text or "in use" in text):
                raise
            logging.getLogger(__name__).info(
                "send2trash file-in-use, retrying in 100ms: %s", path
            )
        time.sleep(0.1)
        QApplication.processEvents()
        send2trash(str(path))

    def _on_library_undelete(self) -> None:
        """라이브러리에서 Ctrl+Z — 마지막 Del 한 항목을 휴지통에서 복원하고 라이브러리에
        다시 추가한다. 디스크 파일이 없던 항목은 라이브러리에만 다시 등록."""
        if not self._undelete_stack:
            return
        snapshot = self._undelete_stack[-1]
        path = snapshot.get("path")

        if path is not None:
            from screen_recorder.core.recycle_bin import is_supported as rb_supported, restore as rb_restore
            if not rb_supported():
                QMessageBox.information(
                    self, "복원 불가",
                    "이 환경에서는 Ctrl+Z 휴지통 복원이 지원되지 않습니다.\n"
                    "Windows 탐색기 휴지통에서 직접 '복원' 해 주세요.",
                )
                return
            ok, reason = rb_restore(path)
            if not ok:
                QMessageBox.warning(
                    self, "복원 실패",
                    f"휴지통에서 복원하지 못했습니다.\n\n사유: {reason}\n\n"
                    f"파일: {path}\n\nWindows 탐색기 휴지통에서 직접 복원해 주세요.",
                )
                return

        # 복원 (또는 미저장 항목) — 라이브러리에 새 entry 로 다시 등록. id 는 새로 발급.
        # 스택에서 제거.
        self._undelete_stack.pop()
        new_entry = self.library_model.add(
            kind=snapshot["kind"],
            thumbnail=snapshot["thumbnail"],
            source_label=snapshot["source_label"],
            display_name=snapshot["display_name"],
            path=path,
            duration_ms=snapshot["duration_ms"],
            origin=snapshot["origin"],
        )
        self.status_bar.state_label.setText(f"↩ 복원: {new_entry.display_name}")
        self.status_bar.state_label.setStyleSheet("color: #5BC07C;")

    def _on_library_open_folder(self, entry_id: int) -> None:
        entry = self.library_model.get(entry_id)
        if entry is None:
            return
        # 파일이 실제로 디스크에 있으면 탐색기에서 그 파일을 '선택된 상태로' 열기
        # (Windows: explorer /select,FILE). 미저장이거나 삭제된 항목은 모드별 기본
        # 저장 폴더만 연다.
        if entry.path is not None and entry.path.exists():
            if self._reveal_in_explorer(entry.path):
                return
            # 폴백 — explorer 호출 실패 시 폴더만 연다.
            folder = entry.path.parent
        elif entry.kind is EntryKind.VIDEO:
            folder = Path(self.app_settings.general.output_dir or default_video_dir())
        else:
            folder = Path(self.app_settings.screenshot.save_dir or default_image_dir())
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _reveal_in_explorer(self, file_path: Path) -> bool:
        """탐색기에서 파일을 '선택된' 상태로 열기. 성공하면 True.

        Windows 는 `explorer.exe /select,FILE` 로 파일이 하이라이트된 채 부모 폴더가
        열린다. 다른 OS 는 미지원 (폴더만 여는 폴백을 호출자가 사용).
        주의: explorer.exe 는 성공해도 exit code 1 을 자주 반환하므로 returncode 로
        실패 판정 금지. fire-and-forget Popen 만 사용.
        """
        import sys
        if sys.platform != "win32":
            return False
        try:
            import subprocess
            # /select 와 파일 경로 사이는 공백이 아니라 콤마로 붙여 한 인자로 전달.
            subprocess.Popen(
                ["explorer.exe", f"/select,{file_path}"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception as e:
            logging.getLogger(__name__).warning(
                "explorer /select failed for %s: %s", file_path, e
            )
            return False

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
        self._persist_settings()

    # ---------- 스크린샷 편집 액션 ----------

    def _current_screenshot_tab(self) -> EditTab | None:
        w = self.tab_area.currentWidget()
        return w if isinstance(w, EditTab) else None

    def _apply_tool_to_current_tab(self, tool_id: str) -> None:
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        # 도구별 마우스 커서 — 사용자가 도형 그리기 모드임을 인지하도록.
        cursor_map = {
            "rect": Qt.CrossCursor,
            "arrow": Qt.CrossCursor,
            "text": Qt.IBeamCursor,
            "crop": Qt.CrossCursor,
            "magic_wand": Qt.PointingHandCursor,
            "select": Qt.ArrowCursor,
            "selection": Qt.CrossCursor,
            "brush": Qt.BlankCursor,       # 링이 위치 표시
            "eraser": Qt.BlankCursor,
            "mask_brush": Qt.BlankCursor,
        }
        tab.canvas.viewport().setCursor(cursor_map.get(tool_id, Qt.ArrowCursor))
        color = QColor(self.app_settings.annotation.last_color)
        th = self.app_settings.annotation.last_thickness
        stack = tab.undo_stack
        # 새 vector 아이템을 만드는 도구만 AnnotationLayer 자동 생성 — select 는 기존
        # 아이템을 잡는 도구라 레이어가 없으면 그냥 빈 동작이면 충분하다. 캡처 직후
        # _reset_to_select_tool 가 select 로 돌려놓을 때 의도치 않게 빈 주석 레이어가
        # 생성되는 문제를 막기 위함.
        if tool_id in ("rect", "arrow", "text"):
            self._ensure_annotation_layer(tab)
        # 주석 도구는 활성 AnnotationLayer 의 자체 scene 으로 이벤트 라우팅 필요.
        ann_scene = self._active_annotation_scene(tab)
        if tool_id == "select":
            tab.canvas.set_tool(SelectTool(), target_scene=ann_scene)
        elif tool_id == "selection":
            # selection 도구는 캔버스의 메인 scene 으로 (annotation 이 아님 — selection 은
            # 모든 레이어 위에 떠 있는 글로벌 사각 영역).
            sel_tool = SelectionTool(tab.selection)
            sel_tool.cursor_requested.connect(
                lambda shape, t=tab: t.canvas.viewport().setCursor(Qt.CursorShape(shape))
            )
            tab.canvas.set_tool(sel_tool)
            self._current_special_tool = None
        elif tool_id == "rect":
            tab.canvas.set_tool(
                RectTool(color, th, tab.canvas.shift_held, stack),
                target_scene=ann_scene,
            )
        elif tool_id == "arrow":
            tab.canvas.set_tool(
                ArrowTool(color, th, tab.canvas.shift_held, stack),
                target_scene=ann_scene,
            )
        elif tool_id == "text":
            tab.canvas.set_tool(
                TextTool(
                    color, stack,
                    live_scene=tab.canvas.scene(),
                    on_commit=lambda: self.tool_palette.set_current_tool("select"),
                ),
                target_scene=ann_scene,
            )
        elif tool_id == "crop":
            # 새 크롭 시작 — 기존 selection 은 정리.
            tab.selection.clear()
            crop_tool = CropTool()
            crop_tool.commit_requested.connect(
                lambda r, t=tab: self._on_crop_committed(t, r)
            )
            crop_tool.cursor_requested.connect(
                lambda shape, t=tab: t.canvas.viewport().setCursor(Qt.CursorShape(shape))
            )
            tab.canvas.set_tool(crop_tool)
            self._current_special_tool = None
        elif tool_id == "brush":
            # 사용자가 LayersPanel 에서 AnnotationLayer 를 활성화한 상태로 브러시를
            # 누르면 도구가 무시되어 "브러시 작동 안 함" 으로 보임 — 가장 위 ImageLayer
            # 로 자동 전환해 호환성 확보.
            self._ensure_active_image_layer(tab)
            brush = RasterBrushTool(tab.stack, color=color,
                                    size=self._raster_brush_size, mode="paint")
            brush.stroke_completed.connect(
                lambda lid, prev, new, t=tab: self._on_raster_paint_completed(t, lid, prev, new, "브러시")
            )
            tab.canvas.set_tool(brush)
            self._current_special_tool = brush
        elif tool_id == "eraser":
            self._ensure_active_image_layer(tab)
            eraser = RasterBrushTool(tab.stack, color=color,
                                     size=self._raster_brush_size, mode="erase")
            eraser.stroke_completed.connect(
                lambda lid, prev, new, t=tab: self._on_raster_paint_completed(t, lid, prev, new, "지우개")
            )
            tab.canvas.set_tool(eraser)
            self._current_special_tool = eraser
        elif tool_id == "magic_wand":
            self._ensure_active_image_layer(tab)
            tool = MagicWandTool(tab.stack, tolerance=self._magic_wand_tolerance)
            tool.commit_requested.connect(
                lambda lid, mask, aff, t=tab: self._on_magic_wand_committed(t, lid, mask, aff)
            )
            tool.preview_changed.connect(
                lambda lid, aff, t=tab: self._on_magic_wand_preview(t, lid, aff)
            )
            tool.cancelled.connect(
                lambda t=tab: t.selection.clear()
            )
            tab.canvas.set_tool(tool)
            self._current_special_tool = tool
        elif tool_id == "mask_brush":
            tool = MaskBrushTool(tab.stack, brush_size=self._mask_brush_size,
                                 mode=self._mask_brush_mode)
            tool.stroke_completed.connect(
                lambda lid, prev, new, t=tab: self._on_mask_brush_completed(t, lid, prev, new)
            )
            tab.canvas.set_tool(tool)
            self._current_special_tool = tool
        else:
            self._current_special_tool = None
        self.annotation_toolbar.set_undo_enabled(tab.undo_stack.canUndo())
        self.annotation_toolbar.set_redo_enabled(tab.undo_stack.canRedo())

    @staticmethod
    def _ensure_annotation_layer(tab: EditTab) -> "AnnotationLayer":
        """AnnotationLayer 가 없으면 가장 위에 하나 추가하고 그 인스턴스를 반환.

        새 캡처/새 캔버스에서는 주석 레이어를 자동 생성하지 않아 레이어 패널이 단순한데,
        rect/arrow/text 도구는 vector 아이템을 담을 scene 이 필요해 선택 시점에 자동
        생성한다 (Photoshop 의 "shape tool" 이 자동으로 shape layer 를 만들 듯).
        활성 레이어는 사용자의 선택을 보존 — 자동 생성된 주석 레이어로 옮기지 않는다.
        """
        for layer in tab.stack.layers:
            if isinstance(layer, AnnotationLayer):
                return layer
        new_id = tab.stack.next_id()
        layer = AnnotationLayer(
            id=new_id, name="레이어", canvas_size=tab.stack.canvas_size
        )
        tab.stack.add_layer(layer)
        return layer

    @staticmethod
    def _ensure_active_image_layer(tab: EditTab) -> None:
        """활성 레이어가 ImageLayer 가 아니면 가장 위 ImageLayer 로 활성을 옮긴다.

        브러시/지우개는 ImageLayer 픽셀에만 작동하는데 사용자가 LayersPanel 에서
        AnnotationLayer 를 클릭하면 활성이 그쪽으로 가 도구가 무반응이 된다 — 도구를
        고른 시점에 자동 보정해 사용성을 올린다.
        """
        active = tab.stack.active_layer()
        if isinstance(active, ImageLayer):
            return
        for layer in reversed(tab.stack.layers):
            if isinstance(layer, ImageLayer):
                tab.stack.set_active_layer(layer.id)
                return

    def _active_annotation_scene(self, tab: EditTab):
        """현재 탭에서 사용할 AnnotationScene 을 고른다.

        활성 레이어가 AnnotationLayer 면 그 scene, 아니면 가장 위 AnnotationLayer 의 scene.
        AnnotationLayer 가 하나도 없으면 None.
        """
        active = tab.stack.active_layer()
        if isinstance(active, AnnotationLayer):
            return active.scene
        for layer in reversed(tab.stack.layers):
            if isinstance(layer, AnnotationLayer):
                return layer.scene
        return None

    def _on_magic_wand_preview(self, tab: EditTab, layer_id: int, affected_local) -> None:
        """마술봉이 미리보기 상태로 들어가거나 빠질 때 호출.

        affected_local 이 None 이면 미리보기 해제 — selection 도 같이 정리.
        있으면 layer-local rect 를 scene 좌표로 변환해 marching-ants 로 표시.
        """
        layer = tab.stack.get_layer(layer_id)
        if not isinstance(layer, ImageLayer) or affected_local is None:
            tab.selection.clear()
            return
        scene_rect = QRect(affected_local)
        scene_rect.translate(int(layer.offset.x()), int(layer.offset.y()))
        tab.selection.set_rect(scene_rect)

    def _on_magic_wand_committed(self, tab: EditTab, layer_id: int,
                                 new_mask, affected_local) -> None:
        """미리보기를 사용자가 Enter/Delete 로 확정 — 마스크 교체 커맨드 push."""
        from image_editor.operations.magic_wand import MagicWandApplyCommand
        cmd = MagicWandApplyCommand(tab.stack, layer_id, new_mask)
        tab.undo_stack.push(cmd)
        # 확정 후 marching ants 는 잠깐 더 표시 — 사용자에게 어디가 사라졌는지 시각화.
        # 사용자가 다른 곳을 클릭하거나 ESC 하면 자연스럽게 해제됨.
        layer = tab.stack.get_layer(layer_id)
        if isinstance(layer, ImageLayer) and affected_local is not None:
            scene_rect = QRect(affected_local)
            scene_rect.translate(int(layer.offset.x()), int(layer.offset.y()))
            tab.selection.set_rect(scene_rect)

    def _on_mask_brush_completed(self, tab: EditTab, layer_id: int, prev, new) -> None:
        cmd = MaskPaintCommand(tab.stack, layer_id, prev, new)
        tab.undo_stack.push(cmd)

    def _on_raster_paint_completed(self, tab: EditTab, layer_id: int, prev, new,
                                   text: str = "브러시") -> None:
        cmd = RasterPaintCommand(tab.stack, layer_id, prev, new, text=text)
        tab.undo_stack.push(cmd)

    def _on_tool_changed(self, tool_id: str) -> None:
        self._apply_tool_to_current_tab(tool_id)
        # 옵션바의 컨텍스트 패널을 도구에 맞춰 토글
        self.annotation_toolbar.set_active_tool(tool_id)

    def _on_tolerance_changed(self, value: int) -> None:
        self._magic_wand_tolerance = value
        if isinstance(self._current_special_tool, MagicWandTool):
            self._current_special_tool.tolerance = value

    def _on_brush_size_changed(self, value: int) -> None:
        self._mask_brush_size = value
        if isinstance(self._current_special_tool, MaskBrushTool):
            self._current_special_tool.brush_size = value

    def _on_brush_mode_changed(self, mode: str) -> None:
        self._mask_brush_mode = mode
        if isinstance(self._current_special_tool, MaskBrushTool):
            self._current_special_tool.mode = mode

    def _on_raster_size_changed(self, value: int) -> None:
        self._raster_brush_size = value
        if isinstance(self._current_special_tool, RasterBrushTool):
            self._current_special_tool.set_size(value)

    def _on_select_all(self) -> None:
        """Ctrl+A — selection 도구로 전환 + 캔버스 전체를 selection 으로 설정.

        도구를 selection 으로 바꿔야 사용자가 모서리/가장자리 핸들을 잡고 영역을
        조정할 수 있다.
        """
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        size = tab.stack.canvas_size
        tab.selection.set_rect(QRect(0, 0, size.width(), size.height()))
        # 도구 팔레트도 selection 으로 토글 — set_current_tool 이 _apply_tool_to_current_tab 호출.
        if self.tool_palette.current_tool() != "selection":
            self.tool_palette.set_current_tool("selection")
            # set_current_tool 이 tool_changed 시그널을 emit 하지만 동일 도구일 땐 안 함.
            # 새로 그렸으니 _apply_tool_to_current_tab 도 호출 (시그널 의존 안 함).
            self._apply_tool_to_current_tab("selection")
            self.annotation_toolbar.set_active_tool("selection")

    def _on_deselect_all(self) -> None:
        """Ctrl+D — 선택 해제."""
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        tab.selection.clear()

    def _on_palette_action(self, action_id: str) -> None:
        """ToolPalette 의 액션 버튼 (one-shot) 라우팅."""
        if action_id == "auto_bg":
            self._on_remove_background()

    # ---------- 드래그-저장 버튼 콜백 ----------
    def _current_image_for_drag(self):
        tab = self._current_screenshot_tab()
        return None if tab is None else tab.image()

    def _current_filename_for_drag(self) -> str:
        tab = self._current_screenshot_tab()
        if tab is None:
            return "image.png"
        sp = tab.saved_path()
        if sp is not None:
            return Path(sp).stem + ".png"
        return f"{tab.source_label()}.png"

    def _on_color_changed(self, color) -> None:
        self.app_settings.annotation.last_color = color.name(QColor.HexRgb)
        self._apply_tool_to_current_tab(self.tool_palette.current_tool())

    def _on_thickness_changed(self, step: int) -> None:
        self.app_settings.annotation.last_thickness = step
        self._apply_tool_to_current_tab(self.tool_palette.current_tool())

    def _on_undo(self) -> None:
        # 라이브러리 list 에 포커스가 있으면 — 사용자가 휴지통에서 되돌리려는 의도.
        # menu_bar.undo_action 은 WindowShortcut 컨텍스트라 LibraryPanel 의 eventFilter
        # 보다 먼저 발화. 여기서 분기해 위임한다.
        if QApplication.focusWidget() is self.library_panel.list_widget:
            if self._undelete_stack:
                self._on_library_undelete()
            return
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
            save_dir = self.app_settings.screenshot.save_dir or str(default_image_dir())
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

    def _suggested_save_path(self, tab) -> Path:
        """미저장 탭의 Save As 다이얼로그 기본 경로 — 사용자의 파일명 패턴을 따른다.

        라이브러리 항목에 사용자 지정 이름(rename) 이 있으면 그걸 우선, 없으면
        screenshot.filename_pattern 으로 빌드. "image.png" 같은 일반 이름이 노출돼
        사용자가 매번 지우고 새로 입력해야 하는 불편 해소.
        """
        from datetime import datetime
        save_dir = Path(self.app_settings.screenshot.save_dir or default_image_dir())
        entry = self._entry_for_current_tab()
        if entry is not None and entry.display_name:
            # display_name 은 보통 확장자 없는 stem — 기본 PNG 확장자 부여.
            base = entry.display_name
            if not Path(base).suffix:
                base = base + "." + (self.app_settings.screenshot.format or "png")
        else:
            base = build_filename(
                pattern=self.app_settings.screenshot.filename_pattern,
                when=datetime.now(),
                mode="screenshot",
                target=tab.source_label(),
                extension=self.app_settings.screenshot.format,
            )
        return save_dir / base

    # ---------- 파일 메뉴 핸들러 (열기 / 저장 / 다른 이름으로 / 내보내기) ----------

    # 지원하는 확장자 (드래그 앤 드롭 / 메뉴 열기 공통).
    IMAGE_EXTS = {".kstudio", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    VIDEO_EXTS = {".mp4", ".gif", ".webm", ".mov", ".avi", ".mkv"}

    def _on_file_new(self) -> None:
        """파일 → 새로 만들기. 클립보드 크기 또는 사용자 입력 사이즈로 빈 EditTab 생성.

        배경은 다이얼로그의 라디오 버튼(투명/흰색) 선택을 따라간다 — 기본은 투명.
        """
        from .new_canvas_dialog import NewCanvasDialog
        dlg = NewCanvasDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        size = dlg.size()
        try:
            tab = EditTab.from_blank(size, fill_white=dlg.fill_white())
        except ValueError as e:
            QMessageBox.warning(self, "새로 만들기 실패", str(e))
            return
        thumb = tab.image().scaled(
            128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        label = f"새 캔버스 {size.width()}×{size.height()}"
        entry = self.library_model.add(
            EntryKind.IMAGE,
            thumbnail=thumb,
            source_label="new",
            display_name=label,
            origin="opened",
        )
        self.tab_area.add_image_tab(tab, entry_id=entry.id, display_name=label)
        self.mode_controller.set_mode(AppMode.IMAGE)
        self._restore_window_for_capture()

    def _on_file_open(self) -> None:
        """파일 → 열기. .kstudio / 일반 raster / 영상 모두 지원."""
        path, _ = QFileDialog.getOpenFileName(
            self, "파일 열기", "",
            "지원 파일 (*.kstudio *.png *.jpg *.jpeg *.webp *.bmp "
            "*.mp4 *.gif *.webm *.mov *.avi *.mkv);;모든 파일 (*.*)",
        )
        if not path:
            return
        self._open_path(Path(path))

    def _open_path(self, p: Path) -> None:
        """확장자 기준으로 이미지/영상 분기."""
        ext = p.suffix.lower()
        if ext in self.IMAGE_EXTS:
            self._open_image_path(p)
        elif ext in self.VIDEO_EXTS:
            self._open_video_path(p)
        else:
            QMessageBox.warning(
                self, "지원하지 않는 파일",
                f"지원하지 않는 형식입니다: {p.suffix}",
            )

    def _open_image_path(self, p: Path) -> None:
        """이미지 또는 .kstudio 파일을 새 EditTab 으로 연다."""
        try:
            tab = EditTab.from_file(p)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "열기 실패", str(e))
            return
        thumb = tab.image().scaled(
            128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        entry = self.library_model.add(
            EntryKind.IMAGE,
            thumbnail=thumb,
            source_label="opened",
            display_name=p.name,
            path=p,
            origin="opened",
        )
        self.tab_area.add_image_tab(tab, entry_id=entry.id, display_name=p.name)
        self.mode_controller.set_mode(AppMode.IMAGE)
        self._restore_window_for_capture()

    # ---------- 드래그 앤 드롭 (외부 파일 → 탭) ----------
    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        md = e.mimeData()
        if md.hasUrls():
            for u in md.urls():
                ext = Path(u.toLocalFile()).suffix.lower()
                if ext in self.IMAGE_EXTS or ext in self.VIDEO_EXTS:
                    e.acceptProposedAction()
                    return
        super().dragEnterEvent(e)

    def dropEvent(self, e: QDropEvent) -> None:
        md = e.mimeData()
        if not md.hasUrls():
            super().dropEvent(e)
            return
        opened = 0
        for u in md.urls():
            local = u.toLocalFile()
            if not local:
                continue
            p = Path(local)
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext in self.IMAGE_EXTS or ext in self.VIDEO_EXTS:
                self._open_path(p)
                opened += 1
        if opened > 0:
            e.acceptProposedAction()
        else:
            super().dropEvent(e)

    def _open_video_path(self, p: Path) -> None:
        """영상 파일을 새 VideoTab 으로 연다."""
        entry = self.library_model.add(
            EntryKind.VIDEO,
            thumbnail=QImage(),
            source_label="opened",
            display_name=p.name,
            path=p,
            duration_ms=0,
            origin="opened",
        )
        self.tab_area.add_video(
            path=p, source_label="opened",
            duration_ms=0, entry_id=entry.id,
        )
        self.mode_controller.set_mode(AppMode.VIDEO)
        self._restore_window_for_capture()

    def _on_file_save(self) -> None:
        """현재 편집 탭을 저장.

        - 저장 경로가 있으면 그 포맷으로 그대로 덮어쓰기.
        - 없으면(첫 저장) 다이얼로그 없이 기본 폴더 + 파일명 패턴 + 기본 포맷으로
          즉시 저장. 사용자가 매 캡처마다 파일명 다이얼로그를 거쳐야 하는 부담 제거.
          다른 이름/위치로 저장하고 싶으면 Ctrl+Shift+S (다른 이름으로 저장) 사용.
        """
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        target = tab.saved_path()
        if target is None:
            target = self._auto_save_path_for(tab)
            if target is None:
                # 폴더 생성 실패 등 — 사용자에게 dialog 로 fallback.
                self._on_file_save_as()
                return
        if not self._save_tab_to_path(tab, target):
            return
        tab.mark_saved(target)
        # 라이브러리 entry path 동기화 (캡처 직후 첫 저장 때 entry.path 가 None 이었음).
        entry = self._entry_for_current_tab()
        if entry is not None and entry.path != target:
            entry.path = target
            self.library_model.rename(entry.id, target.name)

    def _auto_save_path_for(self, tab) -> Path | None:
        """첫 Ctrl+S 시 다이얼로그 없이 쓸 자동 경로. 기본 이미지 폴더 + 파일명 패턴.
        라이브러리 entry 에 display_name 이 있으면 그걸 우선 사용.
        실패 시 None — 호출자가 Save As 로 fallback."""
        from datetime import datetime
        try:
            save_dir = Path(self.app_settings.screenshot.save_dir or default_image_dir())
            save_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        entry = self._entry_for_current_tab()
        if entry is not None and entry.display_name:
            base = entry.display_name
            if not Path(base).suffix:
                base = base + "." + (self.app_settings.screenshot.format or "png")
        else:
            base = build_filename(
                pattern=self.app_settings.screenshot.filename_pattern,
                when=datetime.now(),
                mode="screenshot",
                target=tab.source_label(),
                extension=self.app_settings.screenshot.format,
            )
        return resolve_collision(save_dir / base)

    def _on_file_save_as(self) -> None:
        """현재 편집 탭을 다른 이름으로 저장. PNG 가 기본, .kstudio/JPG/WebP/BMP 도 선택 가능."""
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        suggested = tab.saved_path() or self._suggested_save_path(tab)
        # PNG 를 가장 먼저 두어 다이얼로그 기본 필터가 되도록 한다 (사용자가 가장 자주 쓰는 포맷).
        filters = (
            "PNG (*.png);;"
            "KStudio (*.kstudio);;"
            "JPEG (*.jpg *.jpeg);;"
            "WebP (*.webp);;"
            "BMP (*.bmp)"
        )
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "다른 이름으로 저장", str(suggested), filters
        )
        if not path:
            return
        p = Path(path)
        # 사용자가 확장자를 안 적었으면 선택한 필터에 맞는 기본 확장자 부여.
        if not p.suffix:
            p = p.with_suffix(self._default_ext_for_filter(selected_filter))
        if not self._save_tab_to_path(tab, p):
            return
        tab.mark_saved(p)

    @staticmethod
    def _default_ext_for_filter(selected_filter: str) -> str:
        sf = (selected_filter or "").lower()
        if "kstudio" in sf:
            return ".kstudio"
        if "png" in sf:
            return ".png"
        if "jpeg" in sf or "jpg" in sf:
            return ".jpg"
        if "webp" in sf:
            return ".webp"
        if "bmp" in sf:
            return ".bmp"
        return ".png"

    def _save_tab_to_path(self, tab: "EditTab", p: Path) -> bool:
        """확장자에 따라 .kstudio(레이어 보존) 또는 raster 평탄화로 저장."""
        ext = p.suffix.lower()
        try:
            if ext == ".kstudio":
                write_kstudio(tab.stack, p)
            elif ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                img = tab.image()
                fmt = "JPG" if ext in (".jpg", ".jpeg") else ext[1:].upper()
                if fmt == "JPG":
                    # JPG 알파 미지원 — 흰 배경 합성
                    bg = QImage(img.size(), QImage.Format_RGB32)
                    bg.fill(Qt.white)
                    painter = QPainter(bg)
                    painter.drawImage(0, 0, img)
                    painter.end()
                    if not bg.save(str(p), "JPG"):
                        raise OSError(f"이미지 저장 실패: {p}")
                else:
                    if not img.save(str(p), fmt):
                        raise OSError(f"이미지 저장 실패: {p}")
            else:
                QMessageBox.warning(self, "저장 실패", f"지원하지 않는 형식입니다: {ext}")
                return False
        except OSError as e:
            QMessageBox.warning(self, "저장 실패", str(e))
            return False
        return True

    def _on_export(self, fmt: str) -> None:
        """PNG/JPG/WebP 로 평탄화 내보내기."""
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        fmt = fmt.lower()
        ext = fmt
        suggested = Path(
            self.app_settings.screenshot.save_dir or default_image_dir()
        ) / f"export.{ext}"
        path, _ = QFileDialog.getSaveFileName(
            self, f"{fmt.upper()} 로 내보내기", str(suggested),
            f"{fmt.upper()} (*.{ext})",
        )
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() != f".{ext}":
            p = p.with_suffix(f".{ext}")
        img = tab.image()
        if fmt == "jpg":
            # JPG 는 알파 미지원 — 흰 배경 위에 합성
            bg = QImage(img.size(), QImage.Format_RGB32)
            bg.fill(Qt.white)
            painter = QPainter(bg)
            painter.drawImage(0, 0, img)
            painter.end()
            ok = bg.save(str(p), "JPG")
        else:
            ok = img.save(str(p), fmt.upper())
        if not ok:
            QMessageBox.warning(self, "내보내기 실패", f"{p}")

    def _on_export_video(self) -> None:
        """현재 활성 영상 탭의 사이드카를 적용한 새 mp4 생성."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from .export_dialog import ExportDialog
        from ..encode.export_pipeline import build_export_args, default_output_path
        from ..encode.export_job import ExportJob

        tab = self.tab_area.current_video_tab() if hasattr(self.tab_area, "current_video_tab") else None
        if tab is None:
            return
        sidecar = tab._edit_controller.sidecar()
        src_path = tab._source_path
        main_duration = tab.player.duration_ms()
        if main_duration <= 0:
            QMessageBox.warning(self, "내보내기", "영상 길이가 확정되지 않았습니다.")
            return

        # 출력 경로 — 기본은 원본 폴더의 _edited.mp4. 사용자 변경 가능.
        default = default_output_path(src_path)
        dst, _ = QFileDialog.getSaveFileName(
            self, "내보낼 파일", str(default), "MP4 (*.mp4)"
        )
        if not dst:
            return
        dst = Path(dst)

        # 영상 해상도 — 첫 프레임 / player surface 크기 사용.
        # 정확한 영상 코덱 해상도는 ffprobe 가 필요하나 surface 크기로 대체 가능.
        surface_w = max(1, tab.player.width())
        surface_h = max(1, tab.player.height())

        try:
            argv, pngs = build_export_args(
                sidecar=sidecar, src_path=src_path, dst_path=dst,
                main_duration_ms=main_duration,
                surface_w=surface_w, surface_h=surface_h,
                ffmpeg_path=self.ffmpeg_path,
            )
        except NotImplementedError as e:
            QMessageBox.warning(self, "내보내기", f"미구현 효과: {e}")
            return

        # 결합 시간축 길이 = ExportJob 의 progress 분모
        from ..effects.timeline import build_combined_timeline
        from ..effects.types.cut import CutEffect
        cuts = [e for e in sidecar.effects if isinstance(e, CutEffect)]
        segs = build_combined_timeline(main_duration, cuts)
        total_combined_ms = segs[-1].combined_end_ms if segs else main_duration

        dialog = ExportDialog(total_duration_ms=total_combined_ms, parent=self)
        job = ExportJob(
            ffmpeg_path=self.ffmpeg_path,
            argv=argv, png_paths=pngs, dst_path=dst,
            total_duration_ms=total_combined_ms,
        )
        job.progress.connect(dialog.set_progress)
        job.finished.connect(dialog.set_finished)
        job.error.connect(dialog.set_error)
        dialog.cancel_requested.connect(job.cancel)
        dialog.open_folder_requested.connect(self._open_in_explorer)
        job.start()
        dialog.show()

    def _open_in_explorer(self, path) -> None:
        """결과 파일을 탐색기에서 선택된 채로 열기."""
        import sys
        import subprocess
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(Path(path))])

    def _on_remove_background(self) -> None:
        """현재 활성 ImageLayer 의 배경을 rembg 로 제거 (마스크 추가).

        실행 전에 모델 선택 다이얼로그(BgRemovalModelDialog) 를 띄워 사용자가 자기
        이미지에 맞는 모델을 고르게 한다 — 일반 사진이면 u2net, UI/그래픽이면
        isnet-general-use 등 입력 종류에 따라 결과 품질이 크게 갈리기 때문.
        rembg 가 모델 로딩 + 추론에 수 초~수십 초 걸릴 수 있어 사용자가 실행 여부를
        알 수 있도록 indeterminate QProgressDialog 를 띄운다. 작업은 QThreadPool 백그라운드.
        """
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        active = tab.stack.active_layer()
        if not isinstance(active, ImageLayer):
            # 활성이 ImageLayer 가 아니면 사진 레이어로 자동 전환 시도 — 브러시·마술봉과
            # 같은 정책. 그래도 ImageLayer 가 하나도 없으면 안내 후 종료.
            self._ensure_active_image_layer(tab)
            active = tab.stack.active_layer()
            if not isinstance(active, ImageLayer):
                QMessageBox.information(
                    self, "배경 제거",
                    "이미지 레이어가 있어야 합니다.",
                )
                return
        # 모델 선택 다이얼로그 — 마지막에 쓴 모델을 기본 선택.
        from .bg_removal_dialog import BgRemovalModelDialog
        dlg = BgRemovalModelDialog(
            current_model=self.app_settings.annotation.bg_removal_model,
            parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        model_name = dlg.selected_model()
        # 다음 호출의 기본값으로 기억.
        self.app_settings.annotation.bg_removal_model = model_name
        cmd = BackgroundRemovalCommand(tab.stack, layer_id=active.id, model_name=model_name)

        # 진행 상황 — 모델 캐시 여부에 따라 다운로드 / 추론 2 단계로 안내.
        from .bg_removal_dialog import (
            is_model_downloaded as _bg_is_cached,
            model_size_mb as _bg_size,
            rembg_cache_dir as _bg_cache_dir,
        )
        was_cached = _bg_is_cached(model_name)
        expected_mb = _bg_size(model_name)
        expected_bytes = expected_mb * 1024 * 1024
        cache_dir = _bg_cache_dir()
        check_path = cache_dir / f"{model_name}.onnx"

        if was_cached:
            initial_text = f"배경 제거 추론 중... ({model_name})"
            progress = QProgressDialog(initial_text, None, 0, 0, self)
        else:
            initial_text = (
                f"모델 다운로드 중... ({model_name}, 0 / {expected_mb} MB)\n"
                "처음 한 번만 받으면 다음부터는 빨라집니다."
            )
            progress = QProgressDialog(initial_text, None, 0, expected_bytes, self)
        progress.setWindowTitle("자동 누끼")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()

        # 다운로드 진행률 추정 — pooch 가 캐시 디렉토리 안에 임시 파일을 만들고 끝나면
        # 최종 이름으로 rename 하므로, "현재 디렉토리 총 크기 - 시작 시점 baseline" 이
        # 다운로드된 바이트 수에 가깝다. 250ms 마다 폴링하며 최종 .onnx 가 등장하면
        # 추론 단계로 넘어가 indeterminate 로 전환.
        def _dir_total_bytes() -> int:
            if not cache_dir.exists():
                return 0
            total = 0
            try:
                for f in cache_dir.iterdir():
                    try:
                        total += f.stat().st_size
                    except OSError:
                        continue
            except OSError:
                return 0
            return total

        baseline_bytes = _dir_total_bytes()
        download_done = [was_cached]   # mutable flag for nested closure

        timer = QTimer(self)
        timer.setInterval(250)

        def _poll() -> None:
            if download_done[0]:
                return
            try:
                # 최종 .onnx 가 완성된 경우 — 다운로드 종료, 추론 단계로 전환
                if check_path.exists() and check_path.stat().st_size > 0:
                    download_done[0] = True
                    progress.setRange(0, 0)   # 추론은 indeterminate
                    progress.setLabelText(f"배경 제거 추론 중... ({model_name})")
                    return
                # 진행률 갱신 — 디렉토리 총 크기 변화를 기준으로
                downloaded = max(0, _dir_total_bytes() - baseline_bytes)
                downloaded = min(downloaded, expected_bytes)
                progress.setValue(downloaded)
                mb_now = downloaded / (1024 * 1024)
                progress.setLabelText(
                    f"모델 다운로드 중... ({model_name}, "
                    f"{mb_now:.1f} / {expected_mb} MB)\n"
                    "처음 한 번만 받으면 다음부터는 빨라집니다."
                )
            except OSError:
                pass

        timer.timeout.connect(_poll)
        if not was_cached:
            timer.start()

        def on_finish(success: bool) -> None:
            timer.stop()
            progress.close()
            if success:
                tab.undo_stack.push(cmd)

        def on_failed(msg: str) -> None:
            timer.stop()
            progress.close()
            QMessageBox.warning(self, "배경 제거 실패", msg)

        cmd.finished.connect(on_finish)
        cmd.failed.connect(on_failed)
        cmd.run_async()

    def _on_image_scale(self) -> None:
        """현재 이미지 탭의 합성 결과를 픽셀/% 입력 받아 리사이즈 → 새 PNG.

        트림 패턴과 동일: 결과는 새 파일 + 라이브러리 entry + 새 탭 + 자동 포커스.
        원본은 그대로 보존 (undo 통합 X — 탭이 별도라 사용자가 닫으면 곧 원복).

        다이얼로그에서 사용자가 "AI 업스케일" 을 체크하면 Real-ESRGAN 4x ONNX
        모델로 추론 후 LANCZOS 로 정확한 목표 크기에 맞춤. 미체크면 LANCZOS 만.
        AI 첫 사용 시 모델 ~67MB 자동 다운로드 (rembg 와 동일한 진행률 UX).
        """
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        img = tab.image()
        if img.isNull() or img.width() <= 0 or img.height() <= 0:
            QMessageBox.information(self, "이미지 크기 변경", "비어있는 이미지입니다.")
            return

        from .scale_dialog import ScaleDialog
        dlg = ScaleDialog(src_w=img.width(), src_h=img.height(), parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        target_w, target_h = dlg.target_size()
        if target_w == img.width() and target_h == img.height():
            return   # 변경 없음 — 사용자 의도 보호 차원에서 no-op.

        # 저장 폴더 — 현재 탭 entry 가 디스크 경로를 갖고 있으면 그 폴더, 아니면 기본.
        entry = self._entry_for_current_tab()
        if entry is not None and entry.path is not None:
            src_for_naming = entry.path
        else:
            base_dir = Path(self.app_settings.screenshot.save_dir or default_image_dir())
            base_dir.mkdir(parents=True, exist_ok=True)
            display = entry.display_name if entry is not None else "image"
            src_for_naming = base_dir / f"{display}.png"

        if dlg.wants_ai_upscale():
            self._run_ai_upscale(img, target_w, target_h, src_for_naming)
            return

        # 일반 LANCZOS 경로
        from screen_recorder.encode.scale import (
            scale_qimage, resolve_scaled_path, save_scaled,
        )
        try:
            out = scale_qimage(img, target_w, target_h)
        except (ValueError, MemoryError) as e:
            QMessageBox.warning(self, "이미지 크기 변경 실패", str(e))
            return

        try:
            dst = resolve_scaled_path(src_for_naming, target_w, target_h)
            dst.parent.mkdir(parents=True, exist_ok=True)
            save_scaled(out, dst)
        except OSError as e:
            QMessageBox.warning(self, "저장 실패", str(e))
            return

        # 결과 파일을 일반 "열기" 흐름으로 통합 — 새 탭 + 라이브러리 entry + 포커스.
        self._open_image_path(dst)
        self.status_bar.state_label.setText(
            f"📐 크기 변경 완료 — {target_w}×{target_h} → {dst.name}"
        )
        self.status_bar.state_label.setStyleSheet("color: #5BC07C;")

    def _run_ai_upscale(
        self,
        img: QImage,
        target_w: int,
        target_h: int,
        src_for_naming: Path,
    ) -> None:
        """AI 업스케일 비동기 흐름 — 모델 다운로드(필요 시) → 추론 → 결과 처리.

        rembg 의 _on_remove_background 와 동일한 패턴: QProgressDialog + 백그라운드
        QRunnable + 시그널 콜백. 다운로드는 결정적 진행률(bytes), 추론은 타일 단위
        진행률, 둘 다 끝나면 finished 시그널로 결과 QImage 수신.
        """
        from screen_recorder.encode import upscale as _up
        from screen_recorder.encode.scale import (
            scale_qimage, resolve_scaled_path, save_scaled,
        )

        model_id = _up.DEFAULT_MODEL_ID
        info = _up.model_info(model_id)
        expected_mb = info["size_mb"]
        expected_bytes = expected_mb * 1024 * 1024
        was_cached = _up.is_model_downloaded(model_id)

        if was_cached:
            initial_text = "AI 업스케일 추론 중..."
            progress = QProgressDialog(initial_text, None, 0, 0, self)
        else:
            initial_text = (
                f"모델 다운로드 중... (0 / {expected_mb} MB)\n"
                "처음 한 번만 받으면 다음부터는 빨라집니다."
            )
            progress = QProgressDialog(initial_text, None, 0, expected_bytes, self)
        progress.setWindowTitle("AI 업스케일")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()

        emitter = _up.start_upscale_async(img, model_id)

        def on_dl(downloaded: int, total: int) -> None:
            # total==0 → 다운로드 단계 종료, 추론 단계로 전환 (indeterminate)
            if total == 0:
                progress.setRange(0, 0)
                progress.setLabelText("AI 업스케일 추론 중...")
                return
            progress.setRange(0, total)
            progress.setValue(downloaded)
            mb_now = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            progress.setLabelText(
                f"모델 다운로드 중... ({mb_now:.1f} / {mb_total:.0f} MB)\n"
                "처음 한 번만 받으면 다음부터는 빨라집니다."
            )

        def on_inf(done: int, total: int) -> None:
            if total <= 0:
                return
            progress.setRange(0, total)
            progress.setValue(done)
            progress.setLabelText(
                f"AI 업스케일 추론 중... ({done} / {total} 타일)"
            )

        def on_finished(upscaled: QImage) -> None:
            progress.close()
            # AI 모델은 정수배 (4x) 출력 → 사용자 입력 픽셀에 LANCZOS 로 맞춤.
            try:
                if upscaled.width() != target_w or upscaled.height() != target_h:
                    final = scale_qimage(upscaled, target_w, target_h)
                else:
                    final = upscaled
            except (ValueError, MemoryError) as e:
                QMessageBox.warning(self, "이미지 크기 변경 실패", str(e))
                return
            try:
                dst = resolve_scaled_path(src_for_naming, target_w, target_h)
                dst.parent.mkdir(parents=True, exist_ok=True)
                save_scaled(final, dst)
            except OSError as e:
                QMessageBox.warning(self, "저장 실패", str(e))
                return
            self._open_image_path(dst)
            self.status_bar.state_label.setText(
                f"🤖 AI 업스케일 완료 — {target_w}×{target_h} → {dst.name}"
            )
            self.status_bar.state_label.setStyleSheet("color: #5BC07C;")

        def on_failed(msg: str) -> None:
            progress.close()
            QMessageBox.warning(self, "AI 업스케일 실패", msg)

        emitter.download_progress.connect(on_dl)
        emitter.inference_progress.connect(on_inf)
        emitter.finished.connect(on_finished)
        emitter.failed.connect(on_failed)

    def _copy_current_screenshot(self) -> None:
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        self._set_clipboard_image_with_filename(self._image_for_clipboard(tab), tab)

    def _image_for_clipboard(self, tab: "EditTab") -> QImage:
        """selection 이 있으면 그 영역만, 없으면 전체 합성 이미지를 반환."""
        full = tab.image()
        if not tab.selection.has_selection():
            return full
        rect = tab.selection.rect()
        if rect is None:
            return full
        # 캔버스 영역 안으로 클램프
        canvas_rect = QRect(0, 0, full.width(), full.height())
        clipped = rect.intersected(canvas_rect)
        if clipped.width() <= 0 or clipped.height() <= 0:
            return full
        return full.copy(clipped)

    def _cut_current_selection(self) -> None:
        """Ctrl+X — selection 영역을 클립보드에 복사한 뒤 활성 ImageLayer 에서 지움.

        selection 이 없으면 전체 합성 복사만 (지우지는 않음).
        """
        tab = self._current_screenshot_tab()
        if tab is None:
            return
        self._set_clipboard_image_with_filename(self._image_for_clipboard(tab), tab)
        # delete_selection 은 selection 이 없으면 no-op — has_selection 가드는 그쪽이 해 줌.
        tab.delete_selection(command_text="잘라내기")

    def _clipboard_filename_for_tab(self, tab: "EditTab") -> str:
        """탭의 정식 PNG 파일명 — Save As 다이얼로그가 제안하는 이름과 동일 규칙.

        디스크 파일이 있으면 그 stem, 없으면 환경설정 파일명 패턴
        (`screenshot_{date}_{time}` 등). 항상 .png 로 강제 (클립보드는 알파 보존
        가능한 PNG 가 안전하다).
        """
        from datetime import datetime
        entry = self._entry_for_current_tab()
        if entry is not None and entry.display_name:
            stem = Path(entry.display_name).stem or entry.display_name
        else:
            built = build_filename(
                pattern=self.app_settings.screenshot.filename_pattern,
                when=datetime.now(),
                mode="screenshot",
                target=tab.source_label(),
                extension="png",
            )
            stem = Path(built).stem
        # 파일명에 부적합한 문자 제거 — 일부 채팅 앱이 첨부 시 파일명 검증한다.
        safe = "".join(c for c in stem if c.isalnum() or c in " ._-").strip() or "screenshot"
        return f"{safe}.png"

    def _set_clipboard_image_with_filename(
        self, img: QImage, tab: "EditTab",
    ) -> None:
        """클립보드에 이미지 + 정식 이름의 파일 URL 둘 다 set.

        QClipboard.setImage 만 쓰면 받는 앱이 'image.png' 같은 일반 이름을 부여한다.
        같은 이미지를 임시 폴더에 정식 이름(Save As 와 동일한 규칙) 으로 저장하고
        그 URL 도 함께 넣어 — file-drop 을 우선하는 앱 (Slack/탐색기/Word) 이 정식
        이름으로 받게 한다. 임시 폴더는 인스턴스 단위로 한 번 만들어 재사용,
        앱 종료 시 정리.
        """
        import shutil
        import tempfile

        mime = QMimeData()
        mime.setImageData(img)

        # 임시 폴더 — 첫 호출 때만 만들고 종료 시 정리.
        if getattr(self, "_clipboard_tmpdir", None) is None:
            self._clipboard_tmpdir = Path(
                tempfile.mkdtemp(prefix="kstudio_clipboard_")
            )
            import atexit
            atexit.register(
                lambda d=self._clipboard_tmpdir: shutil.rmtree(d, ignore_errors=True)
            )

        try:
            base = self._clipboard_filename_for_tab(tab)
            tmp_path = self._clipboard_tmpdir / base
            n = 1
            # 같은 이름이 이미 있으면 _N 번호 붙여 충돌 회피 — 같은 탭을 여러 번
            # 복사하면 매번 새 임시 파일이 생긴다.
            while tmp_path.exists():
                n += 1
                if n > 999:
                    raise OSError("clipboard temp filename collision")
                tmp_path = self._clipboard_tmpdir / f"{Path(base).stem}_{n}.png"
            if img.save(str(tmp_path), "PNG"):
                mime.setUrls([QUrl.fromLocalFile(str(tmp_path))])
        except OSError:
            # 임시 파일 저장이 실패하더라도 이미지 클립보드는 동작하도록 — 정식
            # 이름은 못 보내도 paste 자체가 막히지는 않음.
            pass

        QApplication.clipboard().setMimeData(mime)

    def _open_save_folder(self) -> None:
        """File → 저장 폴더 열기. 현재 모드에 맞는 폴더(이미지/영상) 를 탐색기로 연다."""
        if self.mode_controller.mode() is AppMode.VIDEO:
            save_dir = self.app_settings.general.output_dir or str(default_video_dir())
        else:
            save_dir = self.app_settings.screenshot.save_dir or str(default_image_dir())
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(save_dir))

    def _toggle_edit_mode_via_menu(self) -> None:
        """Edit → 편집 모드 토글. 현재 탭이 VideoTab 이면 편집 모드 토글."""
        tab = self.tab_area.currentWidget()
        if isinstance(tab, VideoTab):
            tab.set_edit_mode(not tab.is_edit_mode_on())

    def _open_sidecar_dir(self) -> None:
        """Edit → 사이드카 폴더 열기. 사이드카 디렉토리를 탐색기로 연다."""
        import subprocess
        import sys
        from screen_recorder.effects import default_sidecar_dir
        d = default_sidecar_dir()
        d.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(d)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(d)])
        else:
            subprocess.Popen(["xdg-open", str(d)])

    def _show_about(self) -> None:
        """도움말 → 정보. QMessageBox.about 한 줄 설명 + 저작권."""
        QMessageBox.about(
            self,
            "KStudio 정보",
            "<h3>KStudio 0.1.0</h3>"
            "<p>Windows 전용 화면 캡처 · 녹화 · 이미지 편집 통합 툴</p>"
            "<p>© 2026 kimyori</p>",
        )

    def _maybe_show_hotkey_preset_dialog(self) -> None:
        """첫 실행(preset_name='') 시 두 차원 프리셋 다이얼로그를 띄움."""
        import os
        if os.environ.get("KSTUDIO_NO_FIRST_RUN_DIALOG"):
            return
        from screen_recorder.core.hotkey_presets import is_first_run
        if not is_first_run(self.app_settings):
            return
        self._open_hotkey_preset_dialog()

    def _open_hotkey_preset_dialog(self) -> None:
        """프리셋 다이얼로그 표시 + 사용자 선택 적용. 첫 실행 / 환경설정 버튼 공용."""
        from .hotkey_preset_dialog import HotkeyPresetDialog
        from screen_recorder.core.hotkey_presets import (
            apply_global_preset, apply_player_preset,
            detect_global_preset, detect_player_preset,
        )
        current_global = detect_global_preset(self.app_settings)
        current_player = detect_player_preset(self.app_settings)
        dialog = HotkeyPresetDialog(
            self,
            current_global=current_global if current_global != "custom" else "kstudio-default",
            current_player=current_player if current_player != "custom" else "kstudio-default",
        )
        dialog.exec()
        applied = False
        if dialog.selected_global is not None:
            apply_global_preset(self.app_settings, dialog.selected_global)
            applied = True
        elif self.app_settings.hotkey.preset_name == "":
            self.app_settings.hotkey.preset_name = "custom"
        if dialog.selected_player is not None:
            apply_player_preset(self.app_settings, dialog.selected_player)
            applied = True
        elif self.app_settings.player_hotkeys.preset_name == "":
            self.app_settings.player_hotkeys.preset_name = "custom"
        self._persist_settings()
        if applied:
            self._reregister_hotkey()
            self._register_editor_shortcuts()
            # 영상 플레이어 스냅샷 단축키 재바인딩.
            if hasattr(self, "_snapshot_shortcut"):
                self._snapshot_shortcut.setKey(
                    QKeySequence(self.app_settings.player_hotkeys.snapshot or "Ctrl+Shift+P")
                )
            self.global_toolbar.set_inline_hotkey("toggle_record", self.app_settings.hotkey.toggle_record)
            self.global_toolbar.set_inline_hotkey("screenshot_region", self.app_settings.hotkey.screenshot_region)

    def _on_intercept_system_keys_changed(self, enabled: bool) -> None:
        """환경설정 토글 즉시 반영 — 매니저에 알리고 핫키 재등록."""
        self.app_settings.hotkey.intercept_system_keys = enabled
        self.hotkeys.set_intercept_enabled(enabled)
        self._reregister_hotkey()
        self._persist_settings()

    def _open_preferences(self) -> None:
        dialog = PreferencesDialog(self.app_settings)
        # 환경설정 안 단축키 패널에서 capture 중에도 글로벌 핫키 해제.
        sp = getattr(dialog, "shortcuts_panel", None)
        if sp is not None:
            sp.hotkey_editing_started.connect(self._pause_hotkey)
            sp.hotkey_editing_finished.connect(self._resume_hotkey)
            # "프리셋 선택…" 버튼 → 같은 다이얼로그 재사용.
            sp.preset_dialog_requested.connect(
                lambda panel=sp: (self._open_hotkey_preset_dialog(),
                                  panel.refresh_after_preset_applied())
            )
            # OS 시스템 단축키 가로채기 토글 — 즉시 hotkey 매니저에 반영.
            sp.intercept_system_keys_changed.connect(self._on_intercept_system_keys_changed)
        dialog.exec()
        # 단축키가 바뀌었을 수 있으므로 재등록 (글로벌 핫키 + 편집기 단축키).
        self._reregister_hotkey()
        self._register_editor_shortcuts()
        # Windows 자동 시작 체크박스가 바뀌었을 수 있으므로 레지스트리 동기화.
        try:
            from screen_recorder.app import windows_autostart  # noqa: PLC0415
            windows_autostart.apply(self.app_settings.preferences.autostart)
        except Exception:
            logging.exception("자동 시작 레지스트리 동기화 실패")
        # 글로벌 툴바 인라인 단축키 표시 동기화 (다이얼로그에서 바뀌었을 수 있음).
        self.global_toolbar.set_inline_hotkey("toggle_record", self.app_settings.hotkey.toggle_record)
        self.global_toolbar.set_inline_hotkey("screenshot_region", self.app_settings.hotkey.screenshot_region)
        # 녹화 상태 도크의 인라인 영상/GIF/사운드 위젯도 다이얼로그가 바꾼 값으로 동기화.
        self.record_status_panel.refresh_from_settings()

    # ---------- 탭 전환 시 옵션바·도구 동기화 ----------

    def _on_active_tab_changed(self) -> None:
        # 라이브러리에서 현재 탭에 해당하는 항목 강조 (탭 → 라이브러리 동기화).
        eid = self.tab_area.current_entry_id()
        if eid is not None:
            self.library_panel.focus_entry(eid)

        tab = self._current_screenshot_tab()
        if tab is None:
            # 활성 탭이 EditTab 이 아니면 레이어 패널은 더미 stack 으로 리셋.
            self._rebind_layers_panel(self._dummy_stack())
            # 영상 탭이면 즉시 포커스를 줘 사용자가 별도 클릭 없이 Space 로 재생 가능.
            self._focus_current_video_tab()
            return
        self.annotation_toolbar.set_current_color(QColor(self.app_settings.annotation.last_color))
        self.annotation_toolbar.set_current_thickness_step(self.app_settings.annotation.last_thickness)
        self.annotation_toolbar.set_zoom_label(tab.canvas.current_zoom())
        self._rebind_layers_panel(tab.stack)

    def _focus_current_video_tab(self) -> None:
        """현재 활성 탭이 VideoTab 이면 포커스를 그 위젯으로 — Space 단축키 즉시 발화.

        다만 사용자가 라이브러리 패널에서 키보드로 작업 중이면(Del / Ctrl+Z 등) 포커스를
        가로채지 않는다 — 그러지 않으면 라이브러리 list_widget 의 eventFilter 가 키 이벤트를
        못 받아 Del/Ctrl+Z 가 먹히지 않는다.
        """
        from .video_tab import VideoTab
        widget = self.tab_area.currentWidget()
        if not isinstance(widget, VideoTab):
            return
        focused = QApplication.focusWidget()
        if focused is self.library_panel.list_widget:
            return
        widget.setFocus()

    def _dummy_stack(self) -> LayerStack:
        return LayerStack(QSize(1, 1))

    def _rebind_layers_panel(self, stack: LayerStack) -> None:
        """LayersPanel 을 새 stack 으로 재바인딩 (dock 안에서 교체)."""
        new_panel = LayersPanel(stack)
        # 메뉴 토글 상태에 맞춰 dock 가시성 동기화
        self.layers_dock.setVisible(self._layers_panel_visible_state())
        old = self.layers_panel
        self.layers_dock.setWidget(new_panel)
        self.layers_panel = new_panel
        old.deleteLater()
        # 영상 모드면 새로 만든 panel 도 disabled 로
        self._apply_layers_panel_enabled_state()

    def _layers_panel_visible_state(self) -> bool:
        """레이어 dock 이 보여야 하는지 — 메뉴 체크 + 이미지 모드.

        영상 모드에서는 레이어가 의미 없어 dock 자체를 숨김 (영역 회수).
        """
        in_image_mode = self.mode_controller.mode() is AppMode.IMAGE
        return in_image_mode and self.menu_bar.layers_visible_action.isChecked()

    def _record_status_visible_state(self) -> bool:
        """녹화 상태 dock 이 보여야 하는지 — 메뉴 체크 + 영상 모드.

        이미지 모드에서는 녹화가 의미 없어 dock 자체를 숨김 (영역 회수).
        """
        in_video_mode = self.mode_controller.mode() is AppMode.VIDEO
        return in_video_mode and self.menu_bar.status_visible_action.isChecked()

    def _apply_layers_panel_enabled_state(self) -> None:
        """현재 모드에 따라 layers_panel 의 활성/비활성 상태 적용 (영상 모드면 disabled)."""
        is_image = self.mode_controller.mode() is AppMode.IMAGE
        self.layers_panel.setEnabled(is_image)

    def _apply_mode_aware_menu_enabled(self) -> None:
        """모드 전용 dock 의 메뉴 항목을 비-적용 모드에서 비활성화 (체크 상태는 보존)."""
        is_image = self.mode_controller.mode() is AppMode.IMAGE
        self.menu_bar.layers_visible_action.setEnabled(is_image)
        self.menu_bar.status_visible_action.setEnabled(not is_image)
        # 이미지 > 배경 제거 / 크기 변경 — 영상 모드에서는 의미 없음.
        self.menu_bar.background_remove_action.setEnabled(is_image)
        self.menu_bar.image_scale_action.setEnabled(is_image)

    def _on_tool_palette_visibility_toggled(self, checked: bool) -> None:
        is_image = self.mode_controller.mode() is AppMode.IMAGE
        self.tool_palette.setVisible(checked and is_image)

    def _on_layers_visibility_toggled(self, _checked: bool) -> None:
        # 메뉴 체크 + 이미지 모드 둘 다 만족할 때만 보임.
        self.layers_dock.setVisible(self._layers_panel_visible_state())

    def _on_record_status_visibility_toggled(self, _checked: bool) -> None:
        # 메뉴 체크 + 영상 모드 둘 다 만족할 때만 보임.
        self.record_status_dock.setVisible(self._record_status_visible_state())

    # ---------- dock 레이아웃 영속화 (모드별 분리) ----------
    def _current_mode_state_attr(self) -> str:
        return ("dock_state_image_b64" if self.mode_controller.mode() is AppMode.IMAGE
                else "dock_state_video_b64")

    def _save_dock_state(self) -> None:
        """현재 모드에 해당하는 dock 레이아웃을 base64 로 저장."""
        try:
            import base64
            state = bytes(self.saveState())
            attr = self._current_mode_state_attr()
            setattr(self.app_settings.preferences, attr, base64.b64encode(state).decode("ascii"))
            # 호환 필드(구버전): 이미지 모드 상태를 그대로 미러링.
            if attr == "dock_state_image_b64":
                self.app_settings.preferences.dock_state_b64 = (
                    self.app_settings.preferences.dock_state_image_b64
                )
        except Exception:
            pass

    def _apply_dock_state_b64(self, b64: str) -> bool:
        if not b64:
            return False
        try:
            import base64
            from PySide6.QtCore import QByteArray
            data = QByteArray(base64.b64decode(b64))
            return bool(self.restoreState(data))
        except Exception:
            return False

    def _restore_dock_state(self) -> None:
        """초기 진입 모드의 dock 레이아웃을 복원. fallback: dock_state_b64."""
        prefs = self.app_settings.preferences
        b64 = (prefs.dock_state_image_b64
               if self.mode_controller.mode() is AppMode.IMAGE
               else prefs.dock_state_video_b64)
        if not self._apply_dock_state_b64(b64):
            self._apply_dock_state_b64(prefs.dock_state_b64)
        self._last_mode = self.mode_controller.mode()

    def _save_dock_state_for_mode(self, mode: AppMode) -> None:
        try:
            import base64
            state = bytes(self.saveState())
            attr = ("dock_state_image_b64" if mode is AppMode.IMAGE
                    else "dock_state_video_b64")
            setattr(self.app_settings.preferences, attr,
                    base64.b64encode(state).decode("ascii"))
        except Exception:
            pass

    def _restore_dock_state_for_mode(self, mode: AppMode) -> None:
        prefs = self.app_settings.preferences
        b64 = (prefs.dock_state_image_b64 if mode is AppMode.IMAGE
               else prefs.dock_state_video_b64)
        # 영상 모드는 기본적으로 layers 가 숨김 — 영상 모드 첫 진입에 저장된 게 없으면
        # restoreState 안 하고 _on_mode_changed 의 layers_dock.setVisible 이 알아서 처리.
        if b64:
            self._apply_dock_state_b64(b64)

    # ---------- 영상 탭 단축키 ----------

    def _snapshot_current_video_frame(self) -> None:
        w = self.tab_area.currentWidget()
        if isinstance(w, VideoTab):
            w._on_snapshot()

    # ---------- 캡처 액션 ----------

    def _on_shot_region_action(self) -> None:
        self._screenshot_ctrl.capture_region()

    def _on_shot_full_action(self) -> None:
        # 글로벌 툴바의 모니터 콤보에서 선택된 인덱스 사용 (-1 = 전체 모니터).
        idx = self.global_toolbar.current_monitor_index()
        self._screenshot_ctrl.capture_full(monitor_index=idx)

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
        # 썸네일은 ffmpeg 호출 (최대 10초 블로킹) — 백그라운드에서 처리하고
        # 우선 placeholder 로 라이브러리/탭 즉시 추가해 UI 응답성 유지.
        p = Path(path)
        duration_ms = self._estimate_duration_ms(p)
        placeholder = QImage(64, 36, QImage.Format_ARGB32)
        placeholder.fill(0xFF222222)
        entry = self.library_model.add(
            EntryKind.VIDEO,
            thumbnail=placeholder,
            source_label=self.global_toolbar.current_target(),
            display_name=p.name,        # 실제 저장된 파일명을 라이브러리에 그대로 표시
            path=p,
            duration_ms=duration_ms,
        )
        self.tab_area.add_video(
            path=p, source_label=entry.source_label,
            duration_ms=duration_ms, entry_id=entry.id,
            display_name=p.name,
            thumbnail=entry.thumbnail,
        )
        self._restore_window_for_capture()
        self.tray.tray.showMessage("녹화 완료", str(p), QSystemTrayIcon.Information, 5000)
        # 썸네일은 백그라운드에서 추출 → 끝나면 LibraryModel 갱신.
        self._extract_thumbnail_async(p, entry.id)

    def _populate_library_from_disk(self) -> None:
        """앱 시작 시 저장 폴더의 기존 파일을 라이브러리에 미리 등록.

        이미지 폴더(screenshot.save_dir)는 이미지/.kstudio, 영상 폴더(general.output_dir)는
        영상/GIF 를 스캔. 두 폴더가 같아도 확장자로 분기하므로 안전.
        썸네일: 이미지는 즉시 디스크에서 로드, 영상은 placeholder 후 백그라운드 ffmpeg 추출.
        모드 필터는 LibraryPanel 이 EntryKind 로 자동 처리.
        """
        img_dir = Path(
            self.app_settings.screenshot.save_dir or default_image_dir()
        )
        vid_dir = Path(
            self.app_settings.general.output_dir or default_video_dir()
        )

        candidates: list[tuple[Path, EntryKind, float]] = []
        for d, exts, kind in (
            (img_dir, self.IMAGE_EXTS, EntryKind.IMAGE),
            (vid_dir, self.VIDEO_EXTS, EntryKind.VIDEO),
        ):
            try:
                if not d.exists() or not d.is_dir():
                    continue
                for p in d.iterdir():
                    if not p.is_file():
                        continue
                    if p.suffix.lower() not in exts:
                        continue
                    try:
                        mtime = p.stat().st_mtime
                    except OSError:
                        continue
                    candidates.append((p, kind, mtime))
            except OSError as e:
                logging.getLogger(__name__).warning("library scan failed for %s: %s", d, e)

        # 오래된 → 최신 순으로 add 하면 LibraryPanel 이 새 항목을 top 에 끼워 넣어
        # 결과적으로 최신이 맨 위에 온다.
        candidates.sort(key=lambda t: t[2])

        placeholder = QImage(64, 36, QImage.Format_ARGB32)
        placeholder.fill(0xFF222222)

        for p, kind, _ in candidates:
            if kind is EntryKind.IMAGE:
                # .kstudio 는 직접 QImage 로 못 읽음 — placeholder.
                if p.suffix.lower() == ".kstudio":
                    thumb = placeholder
                else:
                    img = QImage(str(p))
                    if img.isNull():
                        thumb = placeholder
                    else:
                        thumb = img.scaled(
                            128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation,
                        )
                self.library_model.add(
                    EntryKind.IMAGE,
                    thumbnail=thumb,
                    source_label="opened",
                    display_name=p.name,
                    path=p,
                    origin="opened",
                )
            else:
                entry = self.library_model.add(
                    EntryKind.VIDEO,
                    thumbnail=placeholder,
                    source_label="opened",
                    display_name=p.name,
                    path=p,
                    duration_ms=0,
                    origin="opened",
                )
                # 백그라운드에서 첫 프레임 썸네일 추출 → 라이브러리 항목 갱신.
                self._extract_thumbnail_async(p, entry.id)

    def _setup_library_disk_watcher(self) -> None:
        """이미지/영상 저장 폴더를 watch — 외부에서 파일이 삭제/이동되면 라이브러리에서도 제거.

        QFileSystemWatcher.directoryChanged 는 폴더 안 어떤 변화든(생성/삭제/이름 변경)
        한 번씩 발화. 짧은 시간 내 여러 번 발화할 수 있어 디바운스 타이머로 묶어 처리.
        """
        img_dir = Path(self.app_settings.screenshot.save_dir or default_image_dir())
        vid_dir = Path(self.app_settings.general.output_dir or default_video_dir())
        # mkdir 은 _populate_library_from_disk 단계에서 안 한다 — 여기서도 강제 생성 안 함.
        # 폴더가 아직 없으면 watch 못 함 → 첫 저장 후엔 watch 가 필요해질 수 있는데,
        # 그땐 다음 앱 실행에서 잡힘. 단순성 우선.
        self._library_disk_watcher = QFileSystemWatcher(self)
        watched: list[str] = []
        for d in (img_dir, vid_dir):
            try:
                if d.exists() and d.is_dir():
                    watched.append(str(d))
            except OSError:
                continue
        if watched:
            self._library_disk_watcher.addPaths(watched)
        # 디바운스: 윈도우에서 파일 한 번 삭제해도 directoryChanged 가 2~3 회 발화하기도 함.
        self._library_prune_timer = QTimer(self)
        self._library_prune_timer.setSingleShot(True)
        self._library_prune_timer.setInterval(150)
        self._library_prune_timer.timeout.connect(self._prune_library_missing_files)
        self._library_disk_watcher.directoryChanged.connect(
            lambda _path: self._library_prune_timer.start()
        )

    def _prune_library_missing_files(self) -> None:
        """디스크에서 사라진 파일이 가리키는 라이브러리 항목을 제거.

        - path 가 None 인 항목(아직 저장되지 않은 세션 캡처/편집)은 건드리지 않는다.
        - 열려 있는 탭은 그대로 두어 미저장 작업이 사라지지 않도록 한다 — 사용자가
          다시 저장하면 다음 외부 변화 감지 때 라이브러리에 다시 추가될 수 있음.
        - 디스크 파일은 이미 외부에서 사라졌으므로 send2trash 호출 불필요.
        """
        for entry in list(self.library_model.entries()):
            if entry.path is None:
                continue
            try:
                still_there = entry.path.exists()
            except OSError:
                still_there = False
            if still_there:
                continue
            self.library_model.remove(entry.id)

    # ---------- 영상 트림 lifecycle ----------

    def _on_trim_requested(self, src_path, in_ms: int, out_ms: int) -> None:
        """VideoTab 에서 트림 요청 — TrimJob 시작.

        한 번에 하나만 진행. 진행 중이면 토스트로 안내 후 무시.
        출력 경로: <원본>_cut_NNN.<ext>, 충돌 시 NNN 증가 (1~999).
        """
        if self._active_trim_job is not None:
            from .toast import show_toast
            show_toast(self, "이미 자르는 중입니다", duration_ms=1500)
            return

        src = Path(src_path)
        stem = src.stem
        suffix = src.suffix
        save_dir = src.parent
        n = 1
        candidate = save_dir / f"{stem}_cut_{n:03d}{suffix}"
        while candidate.exists():
            n += 1
            if n > 999:
                from .toast import show_toast
                show_toast(self, "출력 파일명 충돌 (>999)", duration_ms=2000)
                return
            candidate = save_dir / f"{stem}_cut_{n:03d}{suffix}"

        job = TrimJob(
            ffmpeg_path=self.ffmpeg_path,
            src=src, dst=candidate,
            in_ms=in_ms, out_ms=out_ms,
        )
        job.finished.connect(self._on_trim_finished)
        job.error.connect(self._on_trim_error)
        self._active_trim_job = job
        self._active_trim_src_path = src
        self._active_trim_dst_path = candidate

        cur = self.tab_area.currentWidget()
        if isinstance(cur, VideoTab):
            self._active_trim_src_widget = cur
        else:
            self._active_trim_src_widget = None

        self.status_bar.state_label.setText(f"✂ 자르는 중... ({src.name})")
        self.status_bar.state_label.setStyleSheet("color: #26C6DA;")
        job.start()

    def _on_trim_finished(self, out_path) -> None:
        """TrimJob 완료 — 라이브러리 + 새 영상 탭 + 자동 포커스 + 원본 in/out 초기화."""
        out = Path(out_path)
        placeholder = QImage(64, 36, QImage.Format_ARGB32)
        placeholder.fill(0xFF222222)
        entry = self.library_model.add(
            EntryKind.VIDEO,
            thumbnail=placeholder,
            source_label="trim",
            display_name=out.name,
            path=out,
            duration_ms=0,
        )
        self.tab_area.add_video(
            path=out, source_label="trim",
            duration_ms=0, entry_id=entry.id,
            display_name=out.name,
            thumbnail=entry.thumbnail,
        )
        self._extract_thumbnail_async(out, entry.id)

        if isinstance(self._active_trim_src_widget, VideoTab):
            try:
                self._active_trim_src_widget._edit_controller.update_trim(0, 0)
            except RuntimeError:
                pass
        self._reset_trim_state()
        self.status_bar.state_label.setText(f"✂ 완료 — {out.name}")
        self.status_bar.state_label.setStyleSheet("color: #5BC07C;")

    def _on_trim_error(self, msg: str) -> None:
        """TrimJob 실패 — 부분 파일 삭제 + 토스트 + ✂ 재활성."""
        if self._active_trim_dst_path is not None:
            try:
                Path(self._active_trim_dst_path).unlink(missing_ok=True)
            except OSError:
                pass
        from .toast import show_toast
        show_toast(self, f"✂ 자르기 실패 — {msg}", duration_ms=3000)
        if isinstance(self._active_trim_src_widget, VideoTab):
            # PlayerControls.set_cut_button_enabled 제거됨 (timeline 통합) — no-op.
            pass
        self._reset_trim_state()
        self.status_bar.state_label.setText("● 대기 중")
        self.status_bar.state_label.setStyleSheet("color: #A0A4AB;")

    def _reset_trim_state(self) -> None:
        self._active_trim_job = None
        self._active_trim_src_widget = None
        self._active_trim_src_path = None
        self._active_trim_dst_path = None

    def _start_filmstrip_extraction(self, entry_id: int) -> None:
        """라이브러리 entry 의 영상에서 필름스트립 N장을 비동기 추출.

        이미 잡이 진행 중이거나 캐시가 있으면 스킵. 추출 결과는 entry.filmstrip 에
        보관하고 현재 열려있는 같은 entry 의 트림 레인에도 즉시 반영.
        """
        if entry_id in self._filmstrip_jobs:
            return
        entry = self.library_model.get(entry_id)
        if entry is None or entry.path is None or entry.duration_ms <= 0:
            return
        if entry.filmstrip:
            return
        if not Path(entry.path).exists():
            return
        job = FilmstripJob(
            ffmpeg_path=self.ffmpeg_path,
            src=entry.path,
            duration_ms=entry.duration_ms,
            count=20,
            thumb_width=96,
        )
        job.finished.connect(lambda imgs, eid=entry_id: self._on_filmstrip_finished(eid, imgs))
        job.error.connect(lambda msg, eid=entry_id: self._on_filmstrip_error(eid, msg))
        self._filmstrip_jobs[entry_id] = job
        job.start()

    @Slot(int, list)
    def _on_filmstrip_finished(self, entry_id: int, images: list) -> None:
        self._filmstrip_jobs.pop(entry_id, None)
        entry = self.library_model.get(entry_id)
        if entry is None:
            return
        entry.filmstrip = images
        widget = self.tab_area.tab_widget_for_entry(entry_id)
        if widget is not None and isinstance(widget, VideoTab):
            widget.timeline.trim_marker_lane.set_filmstrip(images)

    @Slot(int, str)
    def _on_filmstrip_error(self, entry_id: int, msg: str) -> None:
        self._filmstrip_jobs.pop(entry_id, None)
        # 실패는 silent — 트림 레인이 검정 배경 그대로 유지.
        import logging
        logging.getLogger(__name__).info("filmstrip extraction failed for entry %s: %s",
                                           entry_id, msg)

    def _extract_thumbnail_async(self, path: Path, entry_id: int) -> None:
        """ffmpeg 으로 첫 프레임 썸네일을 비동기 추출 → LibraryModel 갱신."""
        import threading
        def _worker():
            img = self._extract_first_frame(path)
            if img.isNull():
                return
            # 메인 스레드에서 모델 업데이트하도록 dispatch.
            from PySide6.QtCore import QMetaObject, Qt as Qt2, Q_ARG
            QMetaObject.invokeMethod(
                self, "_apply_thumbnail",
                Qt2.QueuedConnection,
                Q_ARG(int, entry_id),
                Q_ARG(QImage, img),
            )
        threading.Thread(target=_worker, daemon=True, name="ThumbnailExtract").start()

    @Slot(int, QImage)
    def _apply_thumbnail(self, entry_id: int, image: QImage) -> None:
        """백그라운드 썸네일 추출 결과를 라이브러리 엔트리에 반영."""
        entry = self.library_model.get(entry_id)
        if entry is None:
            return
        entry.thumbnail = image
        # 라이브러리 패널이 갱신되도록 entry_renamed 또는 직접 view refresh —
        # 가장 간단한 방법: model 의 entry_added 처럼 re-emit 은 어려우므로,
        # rename 시그널을 같은 이름으로 emit 해 list 갱신을 유도.
        try:
            self.library_model.entry_renamed.emit(entry_id, entry.display_name)
        except Exception:
            pass
        # 녹화 직후 만들어진 VideoTab 은 placeholder 썸네일로 시작하므로 실제 첫 프레임이
        # 추출되면 플레이어에도 반영해야 한다 (그렇지 않으면 첫 재생 전까지 회색 화면).
        widget = self.tab_area.tab_widget_for_entry(entry_id)
        if widget is not None and hasattr(widget, "player"):
            widget.player.set_thumbnail(image)

    def _on_error(self, msg: str):
        QMessageBox.warning(self, "에러", msg)

    def _force_quit_app(self) -> None:
        """트레이 메뉴 '종료' 또는 명시적 quit 경로 — 진짜로 앱을 끝낸다."""
        self._force_quit = True
        # close() 가 closeEvent 를 발생시키며 _force_quit 플래그로 분기.
        self.close()
        QApplication.instance().quit()

    def _wait_for_recording_finalize(self) -> None:
        """녹화 종료 후 daemon finalize 스레드가 끝날 때까지 modal 로 대기 (최대 60s).

        controller.recording_finished 시그널이 mp4/gif 헤더 기록 완료를 알린다. 그 시그널을
        받기 전에 closeEvent 를 accept 하면 QApplication.quit() 가 daemon 스레드를 끊어
        손상된 영상 파일이 남는다. 사용자에겐 indeterminate progress 만 보여 주고, 60s
        내에 안 끝나면 그냥 진행 (인코더가 뻗은 비정상 상황 — 더 막아도 의미 없음)."""
        from PySide6.QtCore import QEventLoop

        progress = QProgressDialog("녹화 파일 마무리 중...", None, 0, 0, self)
        progress.setWindowTitle("종료")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()

        loop = QEventLoop(self)
        def _done(_path: str = "") -> None:
            loop.quit()
        self.controller.recording_finished.connect(_done)
        # 안전 타임아웃 — 인코더가 뻗어 시그널이 안 오는 경우를 위한 fallback.
        QTimer.singleShot(60_000, loop.quit)
        try:
            loop.exec()
        finally:
            try:
                self.controller.recording_finished.disconnect(_done)
            except (TypeError, RuntimeError):
                pass
            progress.close()

    def _start_mcp_bridge(self) -> None:
        """MCP HTTP 브리지 시작 — 환경설정에서 enabled 일 때만 호출.

        토큰이 비어 있으면 자동 생성해 settings 에 저장. 포트 0 은 OS 자동 할당
        (실제 포트는 settings.mcp.port 에 저장돼 다음 실행에도 같은 포트 시도).
        """
        from screen_recorder.mcp.bridge_server import BridgeServer, generate_token
        from screen_recorder.mcp.ui_dispatcher import UIDispatcher

        cfg = self.app_settings.mcp
        if not cfg.token:
            cfg.token = generate_token()
        self._mcp_dispatcher = UIDispatcher(self)
        self._mcp_bridge = BridgeServer(
            window=self,
            dispatcher=self._mcp_dispatcher,
            token=cfg.token,
            port=cfg.port,
        )
        try:
            actual = self._mcp_bridge.start()
            cfg.port = actual
        except OSError as e:
            self._mcp_bridge = None
            self._mcp_dispatcher = None
            QMessageBox.warning(
                self, "MCP 브리지 시작 실패",
                f"MCP HTTP 브리지를 시작할 수 없습니다: {e}",
            )

    def _stop_mcp_bridge(self) -> None:
        if self._mcp_bridge is not None:
            try:
                self._mcp_bridge.stop()
            except Exception:   # noqa: BLE001
                pass
            self._mcp_bridge = None
            self._mcp_dispatcher = None

    def closeEvent(self, e):
        # X 버튼은 트레이로 숨김 (실제 종료는 트레이 메뉴 '종료').
        if not getattr(self, "_force_quit", False):
            e.ignore()
            self.hide()
            # 트레이 안내는 최초 1회만 — 매번 띄우면 알람 피로도 증가.
            if not getattr(self, "_tray_hint_shown", False):
                try:
                    self.tray.tray.showMessage(
                        "KStudio",
                        "트레이에서 계속 실행 중입니다. 종료하려면 트레이 아이콘 우클릭 → '종료'.",
                        QSystemTrayIcon.Information, 3000,
                    )
                except Exception:
                    pass
                self._tray_hint_shown = True
            return
        # 실제 종료 경로 — 녹화 중이면 사용자에게 확인.
        if self.controller.state != RecorderState.IDLE:
            ret = QMessageBox.question(self, "종료", "녹화 중입니다. 정지하고 닫을까요?")
            if ret == QMessageBox.Yes:
                self._on_stop_clicked()
            else:
                e.ignore()
                self._force_quit = False  # 종료 취소 시 플래그 리셋
                return
        # mp4/gif 인코더의 finalize 가 백그라운드 daemon 스레드에서 진행되는데 closeEvent
        # 가 즉시 accept 되면 QApplication.quit() 가 그 스레드를 도중 차단해 마지막 청크가
        # 헤더에 안 반영된 손상된 영상이 생긴다. 사용자가 stop 직후 바로 닫는 케이스도
        # 포함되도록 controller 의 finalizing 플래그를 본다 (state 기반은 이미 IDLE 이라
        # 놓침).
        if self.controller.is_finalizing():
            self._wait_for_recording_finalize()
        # 메인 창 위치/크기 영속화 (app/main.py 의 종료 hook 이 settings.save 호출)
        g = self.geometry()
        self.app_settings.screenshot.viewer_x = g.x()
        self.app_settings.screenshot.viewer_y = g.y()
        self.app_settings.screenshot.viewer_w = g.width()
        self.app_settings.screenshot.viewer_h = g.height()
        # dock 레이아웃 영속화 — 현재 모드 기준.
        self._save_dock_state_for_mode(self.mode_controller.mode())
        self.hotkeys.shutdown()
        self._stop_mcp_bridge()
        self._hide_border()
        e.accept()
