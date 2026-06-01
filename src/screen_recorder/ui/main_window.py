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
import os
import sys
from pathlib import Path
from typing import Optional
import pygetwindow as gw

from PySide6.QtCore import (
    Qt, QMimeData, QRect, QSize, QTimer, QUrl, Slot,
)
from PySide6.QtGui import (
    QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QGuiApplication,
    QKeySequence, QShortcut,
)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QToolBar,
    QDockWidget, QFileDialog, QMessageBox, QApplication, QSystemTrayIcon,
    QInputDialog, QProgressDialog, QDialog, QScrollArea, QFrame,
)

from screen_recorder.core.controller import RecorderController
from screen_recorder.core.settings import (
    AppSettings, default_image_dir, default_video_dir,
)
# NOTE: settings_path / save 를 *이름으로* import 하지 마세요 — 테스트 격리
# (conftest 의 isolate_user_settings fixture) 가 `core.settings.<name>` 만
# monkeypatch 하기 때문에 import-by-name 은 우회됩니다 (2026-05-13 사고: pytest 가
# 사용자 실제 settings.json 을 defaults 로 덮어쓴 회귀). 항상 모듈 attribute 로 호출.
from screen_recorder.core import settings as _settings_module
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
from .capture_exclude import exclude_from_capture, include_in_capture
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
from .agent.chat_panel import ChatPanel
from screen_recorder.agent import AgentRuntime, VideoTools, VideoSessionAdapter
from screen_recorder.agent.runtime import AgentMessage, AgentEvent
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


class _MainWindowVideoSession:
    """AgentTools 가 활성 영상 탭 상태를 읽기 위한 어댑터 (VideoSessionAdapter Protocol).

    매 호출마다 tab_area 를 재조회 — 탭 전환·재로드 시 자동으로 새 상태 반영.
    """
    def __init__(self, main_window: "MainWindow") -> None:
        self._mw = main_window

    def _active(self) -> Optional["VideoTab"]:
        tab_area = getattr(self._mw, "tab_area", None)
        if tab_area is None or not hasattr(tab_area, "current_video_tab"):
            return None
        return tab_area.current_video_tab()

    def has_active_video(self) -> bool:
        return self._active() is not None

    def source_path(self) -> Optional[str]:
        t = self._active()
        return t.source_path() if t else None

    def duration_ms(self) -> int:
        t = self._active()
        return t.duration_ms() if t else 0

    def source_duration_ms(self) -> int:
        """원본 파일 길이 (cut/trim *전*). duration_ms 는 적용 *후*.

        2026-05-14: 에이전트가 duration_ms (combined, 2:00) 만 보고 "이 영상은 2분" 이라고
        보고 → 사용자는 파일이 3:24 임을 알고 있어 환각으로 오해. 둘 다 노출 필요.
        """
        t = self._active()
        if t is None:
            return 0
        try:
            return int(t.source_duration_ms())
        except (AttributeError, TypeError):
            return 0

    def position_ms(self) -> int:
        t = self._active()
        return t.position_ms() if t else 0

    def sidecar(self):
        t = self._active()
        return t.sidecar() if t else None

    def list_video_tabs(self) -> list[dict]:
        """현재 열려있는 모든 영상 탭 (Phase 33 멀티 영상 인식)."""
        tab_area = getattr(self._mw, "tab_area", None)
        if tab_area is None:
            return []
        tabs_attr = getattr(tab_area, "_tabs", None)
        if tabs_attr is None:
            return []
        from screen_recorder.ui.video_tab import VideoTab
        active = tab_area.current_video_tab() if hasattr(tab_area, "current_video_tab") else None
        out: list[dict] = []
        for i, entry in enumerate(tabs_attr):
            widget = entry[0] if entry else None
            if not isinstance(widget, VideoTab):
                continue
            try:
                path = widget.source_path()
                label = widget.source_label() if hasattr(widget, "source_label") else ""
            except Exception:
                continue
            out.append({
                "index": i,
                "label": label,
                "path": path,
                "is_active": widget is active,
            })
        return out

    def list_broll_sources(self) -> list[dict]:
        """broll 으로 사용 가능한 영상 파일 후보 — 라이브러리 + 열린 탭.

        Claude 가 broll 효과를 propose 하려면 실제 존재하는 파일 경로가 필요. 추측 금지.
        반환: [{label, path, source('library'|'tab'), duration_ms?}].
        """
        out: list[dict] = []
        seen_paths: set[str] = set()
        # 라이브러리에서 video kind 만.
        lib = getattr(self._mw, "library_model", None)
        if lib is not None:
            try:
                from screen_recorder.ui.library_model import EntryKind
                for entry in lib.entries(kind=EntryKind.VIDEO):
                    p = entry.path
                    if p is None:
                        continue
                    key = str(p)
                    if key in seen_paths:
                        continue
                    seen_paths.add(key)
                    out.append({
                        "label": entry.display_name or entry.source_label or key,
                        "path": key,
                        "source": "library",
                        "duration_ms": int(getattr(entry, "duration_ms", 0) or 0),
                    })
            except Exception:
                pass
        # 열린 탭 — 라이브러리에 이미 있으면 dedupe.
        for tab in self.list_video_tabs():
            p = tab.get("path")
            if not p or p in seen_paths:
                continue
            seen_paths.add(p)
            out.append({
                "label": tab.get("label") or p,
                "path": p,
                "source": "tab",
            })
        return out


class _MainWindowDocumentSession:
    """문서 도구가 활성 Markdown 탭을 읽기 위한 어댑터 (DocumentSessionAdapter Protocol).

    매 호출마다 tab_area 재조회 — 탭 전환 시 자동 반영. 읽기 전용 — 실제 수정은
    AgentRuntime.document_edit_requested → MainWindow._on_agent_document_edit (UI 스레드).
    """
    def __init__(self, main_window: "MainWindow") -> None:
        self._mw = main_window

    def _active(self):
        from .markdown_tab import MarkdownTab
        tab_area = getattr(self._mw, "tab_area", None)
        if tab_area is None:
            return None
        w = tab_area.currentWidget()
        return w if isinstance(w, MarkdownTab) else None

    def has_active_document(self) -> bool:
        return self._active() is not None

    def read_text(self) -> Optional[str]:
        t = self._active()
        return t.editor.toPlainText() if t is not None else None

    def document_path(self) -> Optional[str]:
        t = self._active()
        if t is None:
            return None
        sp = t.saved_path()
        return str(sp) if sp is not None else None

    def is_dirty(self) -> bool:
        t = self._active()
        return bool(t.needs_save()) if t is not None else False


class _MainWindowTranscriptContext:
    """자막 도구가 캐시 위치 + 모델 크기 결정용 (TranscriptContext Protocol)."""
    def __init__(self, main_window: "MainWindow") -> None:
        self._mw = main_window

    def sidecar_dir(self):
        return self._mw._resolve_sidecar_dir()

    def source_hash(self) -> Optional[str]:
        from screen_recorder.effects import compute_video_hash
        tab_area = getattr(self._mw, "tab_area", None)
        if tab_area is None or not hasattr(tab_area, "current_video_tab"):
            return None
        tab = tab_area.current_video_tab()
        if tab is None:
            return None
        sc = tab.sidecar()
        if sc and sc.source_hash:
            return sc.source_hash
        try:
            from pathlib import Path
            return compute_video_hash(Path(tab.source_path()))
        except Exception:
            return None

    def default_model_size(self) -> str:
        try:
            return self._mw.app_settings.agent.whisper_model_size or "base"
        except AttributeError:
            return "base"


class _DockCloseFilter(QObject):
    """dock 의 X 버튼 close 만 잡아 menu_check 를 false 로. setVisible(False) 는 안 잡힘."""
    def __init__(self, dock_action_map: dict) -> None:
        super().__init__()
        self._map = dict(dock_action_map)

    def add(self, dock, action) -> None:
        """lazy 생성된 dock (예: ImageGenDock) 을 사후 등록."""
        self._map[dock] = action

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Close:
            action = self._map.get(obj)
            if action is not None:
                action.setChecked(False)
        return False  # 이벤트 자체는 통과 (dock 정상 close)


def _palette_name_for_mode(mode: AppMode) -> str:
    """AppMode → theme.PALETTES 키. 영상=video(시안)/이미지=image(emerald)/문서=document(amber)."""
    if mode is AppMode.VIDEO:
        return "video"
    if mode is AppMode.DOCUMENT:
        return "document"
    return "image"


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
        # 모드 전환 시 그 모드의 마지막 활성 탭으로 복원하기 위한 기록.
        # 탭 전환 시 _on_active_tab_changed 가 갱신.
        self._last_entry_per_mode: dict[AppMode, int] = {}
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
        # 종료 시점이 최대화 상태였으면 windowState 에 플래그를 미리 세팅 — hidden 상태에서
        # 적용해도 Qt 가 첫 show() 시 자동 반영. main.py 의 show() 흐름이나 트레이 모드
        # (show 안 함) 둘 다 영향 없음. 사용자가 일반 크기로 줄이면 setGeometry 좌표/크기로 복귀.
        if getattr(s, "viewer_maximized", False):
            self.setWindowState(self.windowState() | Qt.WindowMaximized)
        # 창을 작게 만드는 것이 차단되지 않도록 최소 크기 명시 (캡처 후 lockup 방지).
        self.setMinimumSize(480, 320)

        self.app_settings = settings
        self.ffmpeg_path = ffmpeg_path

        # ---------- 모델 / 컨트롤러 멤버 ----------
        self.library_model = LibraryModel()
        # 열린 Markdown 문서 탭의 entry_id → 경로 (Phase 1: 라이브러리 미통합, 자체 추적).
        self._markdown_paths: dict[int, Path] = {}
        # settings 에 저장된 마지막 모드로 시작 — 잘못된 값이면 IMAGE 폴백.
        try:
            saved_mode = AppMode(self.app_settings.preferences.last_mode)
        except ValueError:
            saved_mode = AppMode.IMAGE
        self.mode_controller = ModeController(saved_mode)
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
        # 창 폭이 좁아지면 글로벌 툴바의 모든 버튼이 다 안 들어가 서로 겹치던 회귀 fix —
        # QScrollArea 로 감싸 폭 부족 시 가로 스크롤로 모든 버튼 접근 가능하게.
        # 세로 스크롤은 절대 금지 (툴바 높이는 항상 고정), frame 도 제거해 시각적 동일.
        self._global_tb_scroll = QScrollArea()
        self._global_tb_scroll.setWidget(self.global_toolbar)
        self._global_tb_scroll.setWidgetResizable(True)
        self._global_tb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._global_tb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._global_tb_scroll.setFrameShape(QFrame.NoFrame)
        # global_toolbar 의 sizeHint 높이 + 스크롤바 여유로 host 높이 고정.
        self._global_tb_scroll.setFixedHeight(self.global_toolbar.sizeHint().height() + 12)
        self._global_tb_host.addWidget(self._global_tb_scroll)
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
                                  self.app_settings.player_hotkeys,
                                  sidecar_dir_provider=self._resolve_sidecar_dir)
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
        from .video.inspectors.arrow_inspector import ArrowInspector        # Phase 20.11
        self.inspector_panel.register_inspector("arrow", ArrowInspector)    # Phase 20.11
        self.inspector_dock = QDockWidget("효과 인스펙터", self)
        self.inspector_dock.setObjectName("InspectorDock")
        self.inspector_dock.setWidget(self.inspector_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.inspector_dock)
        self.inspector_dock.hide()   # 기본 숨김

        # ---------- Claude 에이전트 채팅 패널 (Phase 33 — 2026-05-13) ----------
        # 사용자가 채팅창에 영상 편집 명령을 자연어로 입력 → Claude Agent SDK 가
        # 도구를 호출해 응답. Phase A 는 read-only 도구 5개만 — 편집은 Phase B+.
        # 시작 시 stop_loop 가 thread 종료를 막아주므로 closeEvent 에서 명시적 stop.
        self._video_session_adapter = _MainWindowVideoSession(self)
        # AgentRuntime 인스턴스 먼저 부분 생성 — VideoTools 가 콜백으로 참조해야 하므로
        # 임시 placeholder 후 실제 인스턴스로 wire-up.
        from screen_recorder.agent.proposals import ProposalQueue
        self._proposal_queue = ProposalQueue()
        # 콜백: VideoTools (worker thread) → AgentRuntime.emit_apply_request → UI slot.
        # AgentRuntime 생성 시 콜백 주입 위해 lambda 로 늦은 바인딩.
        self._transcript_ctx = _MainWindowTranscriptContext(self)
        self._document_session_adapter = _MainWindowDocumentSession(self)
        self._video_tools = VideoTools(
            self._video_session_adapter,
            ffmpeg_path=str(self.ffmpeg_path) if self.ffmpeg_path else None,
            proposal_queue=self._proposal_queue,
            on_apply=lambda props, fut: self.agent_runtime.emit_apply_request(props, fut),
            transcript_ctx=self._transcript_ctx,
            on_download_whisper=lambda size, fut: self.agent_runtime.emit_whisper_download_request(size, fut),
            document_adapter=self._document_session_adapter,
            on_document_edit=lambda action, fut: self.agent_runtime.emit_document_edit_request(action, fut),
        )
        self.agent_runtime = AgentRuntime(
            self._video_tools,
            cwd=Path(__file__).resolve().parents[3],  # 프로젝트 루트
            parent=self,
        )
        self.agent_runtime.proposals_apply_requested.connect(
            self._on_agent_proposals_apply,
        )
        self.agent_runtime.whisper_download_requested.connect(
            self._on_agent_whisper_download_requested,
        )
        self.agent_runtime.document_edit_requested.connect(
            self._on_agent_document_edit,
        )
        # 저장된 모델 ID + 추론 표시 토글 복원.
        saved_model_id = getattr(self.app_settings.agent, "model_id", None)
        saved_show_thinking = getattr(self.app_settings.agent, "show_thinking", True)
        self.agent_chat_panel = ChatPanel(
            self,
            initial_model_id=saved_model_id,
            initial_show_thinking=saved_show_thinking,
            plan_gate=self.agent_runtime.plan_gate(),
            # agent 주입 — ChatPanel 의 _on_model_changed 가 set_model 을 직접 호출하고
            # 가드 차단 시 콤보 fallback. signal → set_model 라인은 제거 (double-fire 방지).
            agent=self.agent_runtime,
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self.agent_chat_panel)
        self.agent_chat_panel.user_submitted.connect(self.agent_runtime.send)
        # NOTE: model_changed → runtime.set_model 직접 연결 제거 — ChatPanel 이 agent.set_model
        # 을 직접 호출 (가드 결과를 즉시 비교해 fallback 결정해야 하므로). preference 저장만 남김.
        self.agent_chat_panel.model_changed.connect(self._on_agent_model_changed)
        self.agent_chat_panel.cancel_requested.connect(self.agent_runtime.cancel)
        self.agent_chat_panel.show_thinking_changed.connect(self._on_agent_show_thinking_changed)
        # 슬래시 명령 — UI 측 정리는 ChatPanel 가 했고, runtime 측 client lifecycle 만.
        self.agent_chat_panel.clear_requested.connect(self.agent_runtime.clear_session)
        self.agent_chat_panel.compact_requested.connect(self.agent_runtime.compact_session)
        # 미리보기 카드 의 적용/취소 버튼 — apply_proposals pending future 의 resolution.
        self.agent_chat_panel.proposals_apply_confirmed.connect(
            self._on_proposals_card_apply_clicked
        )
        self.agent_chat_panel.proposals_apply_canceled.connect(
            self._on_proposals_card_cancel_clicked
        )
        self.agent_chat_panel.whisper_download_confirmed.connect(
            self._on_whisper_card_download_clicked
        )
        self.agent_chat_panel.whisper_download_canceled.connect(
            self._on_whisper_card_cancel_clicked
        )
        # 모델 다운로드 진행률 → GlobalToolbar 의 라벨 (설정 버튼 왼쪽).
        # 사용자가 ModelDownloadWindow 를 닫아도 진행률 잃지 않게.
        self.agent_chat_panel.download_progress_changed.connect(
            self.global_toolbar.set_download_progress
        )
        self.agent_chat_panel.download_finished.connect(
            self.global_toolbar.clear_download_progress
        )
        # apply pending 상태 — Claude 의 apply_proposals 호출이 사용자 버튼 기다리는 동안 보관.
        self._pending_apply_proposals: list = []
        self._pending_apply_future = None
        # Whisper 다운로드 pending 상태.
        self._pending_whisper_size: Optional[str] = None
        self._pending_whisper_future = None
        # 이미지 생성 별창 (2026-05-27: dock → 비모달 dialog 로 변경).
        # lazy 생성 (사용자가 메뉴 "이미지 생성" / Ctrl+Shift+G / 도구 팔레트 첫 클릭 시).
        # 미사용 사용자에게 PixArtSigmaPipeline import / VRAM 영향 없음.
        self.image_gen_dialog = None  # type: ignore[assignment]
        self.agent_runtime.message_received.connect(self.agent_chat_panel.append_message)
        self.agent_runtime.event_received.connect(self.agent_chat_panel.append_event)
        # AgentRuntime 도 저장된 모델로 동기화 (첫 send 전에).
        # ChatPanel 의 __init__ 에서 의존성 가드 적용 후라, current_model_id() 는
        # 항상 가용한 모델 (의존성 OK 인 것) — 가드 트리거 안 함.
        try:
            self.agent_runtime.set_model(self.agent_chat_panel.current_model_id())
        except (RuntimeError, AttributeError):
            pass
        # 시작 시 의존성 강등 메시지 — settings 의 모델이 의존성 없어 강등됐으면 알림.
        # (그렇지 않으면 사용자가 모르게 모델이 sonnet 으로 바뀐 채로 시작 — 헷갈림.)
        self.agent_chat_panel.emit_startup_warnings()
        # 대화 영속화 — 이전 세션 기록 복원 + 종료 시 자동 저장.
        try:
            from screen_recorder.agent.chat_history import default_history_path
            self.agent_chat_panel.set_history_path(default_history_path())
        except Exception:
            logging.exception("chat history wiring failed")
        # 인스펙터 효과 변경 → 현재 활성 VideoTab 에만 전달 (단일 연결).
        # per-tab 연결 방식은 탭 N 개 열면 N 번 발화해 비활성 탭 사이드카도 덮어쓰는
        # 데이터 무결성 버그를 일으킴 (Stage 2 에서 도입, Stage 3a 에서 최초 노출).
        self.inspector_panel.effect_changed.connect(self._on_inspector_effect_changed)
        # 인스펙터 내 삭제 버튼(Stage 5+) → 현재 활성 탭의 EditController.remove_effect.
        self.inspector_panel.effect_deleted.connect(self._on_inspector_effect_deleted)
        # SpeedInspector 의 전역 배속 토글 → settings 영속 + 모든 영상 탭 적용.
        self.inspector_panel.speed_effects_global_toggled.connect(
            self._on_global_speed_effects_change
        )
        # 시작 시 settings 의 저장된 상태를 패널에 주입 (앞으로 만들어지는 SpeedInspector 에 반영).
        self.inspector_panel.set_speed_effects_enabled(
            self.app_settings.preferences.speed_effects_enabled
        )

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

        # Phase 23: dock 가시성 메뉴 액션 상태를 settings 에서 복원 (X 닫음 영속).
        # 첫 show 후 _restore_initial_dock_layout 가 enforce_dock_visibility 로 이 상태를 적용.
        prefs = self.app_settings.preferences
        for action, attr, default in (
            (self.menu_bar.library_visible_action, "library_dock_visible", True),
            (self.menu_bar.layers_visible_action, "layers_dock_visible", True),
            (self.menu_bar.status_visible_action, "record_status_dock_visible", True),
            (self.menu_bar.agent_panel_visible_action, "agent_panel_visible", True),
            (self.menu_bar.image_gen_visible_action, "image_gen_dock_visible", False),
        ):
            action.blockSignals(True)
            action.setChecked(bool(getattr(prefs, attr, default)))
            action.blockSignals(False)

        # dock 레이아웃 복원은 첫 show *이후* 로 미룬다 (showEvent → _restore_initial_dock_layout).
        # 첫 show 이전 restoreState 는 일부 저장 레이아웃(특히 문서 모드 저장본)에서 Qt paint
        # 단계 크래시 유발 (2026-05-29 사용자 보고: 문서 모드로 종료 후 재시작 시 즉시 종료).

        # 영속화된 가시성 적용 (2026-05-27):
        # - agent: 메뉴 신호 connection 시점에 이미 토글 처리되므로 setVisible 만 명시.
        # - image_gen: lazy 생성이라 settings 가 True 면 시작 시 즉시 생성.
        self.agent_chat_panel.setVisible(
            self.menu_bar.agent_panel_visible_action.isChecked()
        )
        if self.menu_bar.image_gen_visible_action.isChecked():
            self._on_image_gen_visibility_toggled(True)

        # Phase 23: 폴더 스캔 대신 "최근 연 파일" 영속 목록 복원.
        # settings.preferences.recent_library_entries 에서 읽어 path.exists() 통과한
        # 것만 라이브러리에 등록. 썸네일은 library_thumbs 캐시에서 즉시 로드, 캐시 미스 시
        # placeholder + 백그라운드 재추출.
        self._load_persisted_library()

        # 라이브러리 변경 시 자동 저장 (디바운스). 외부 삭제 시 정리도 같은 경로로.
        self._setup_library_persistence()

        # MCP HTTP 브리지 — 환경설정에서 토글된 경우만 시작. 토큰이 비어 있으면
        # 자동 생성해 settings 에 영속화 (다음 실행에도 같은 토큰 유지 — CLI 가
        # 매번 재등록 안 해도 됨). 회귀 fix: 이전엔 이 블록이 _enable_perf_diag 안에
        # 잘못 들어가 있어 KSTUDIO_PERF_DIAG=1 일 때만 _mcp_bridge 가 만들어졌고,
        # 일반 사용자는 closeEvent → _stop_mcp_bridge 에서 AttributeError 로 죽었음.
        from screen_recorder.mcp.pending_requests import PendingRequestStore
        self._mcp_bridge = None
        self._mcp_dispatcher = None
        self._mcp_request_store = PendingRequestStore()   # async 도구 결과 보관
        if self.app_settings.mcp.enabled:
            self._start_mcp_bridge()

        # 문서(WebEngine) 미리보기를 처음 만들 때 Chromium 프로세스 spawn + 최상위 창
        # compositing 전환으로 창 전체가 한 번 깜빡이는 문제(2026-05-29 사용자 보고:
        # "문서 모드 처음 들어갈 때 창이 닫혔다 열리는 듯"). 1×1 로 *보이는* WebEngine
        # 자식을 미리 띄워 compositing 을 첫 show 에 묻어가게 한다 → 이후 실제 문서 탭은
        # 추가 자식이라 재깜빡임이 없다. 상시 Chromium 비용을 영상/이미지 전용 사용자에게
        # 지우지 않도록 last_mode=="document" 일 때만, 비WebEngine/테스트 환경은 제외.
        self._webengine_prewarm = None
        self._maybe_prewarm_webengine()

        # 초기화 끝 — 이제부터 사용자 액션에 의한 persist 허용.
        self._initializing = False

        # 5배속 재생 시 점진적 정지 현상 진단용 로깅. 환경변수
        # KSTUDIO_PERF_DIAG=1 일 때만 활성 — 평소엔 비용 0. 카운터는
        # SegmentPlaybackController / PlayerWidget 가 emit 마다 증가시키고
        # 5초마다 메모리/스레드/ffmpeg 프로세스 수와 함께 로그.
        if os.environ.get("KSTUDIO_PERF_DIAG") == "1":
            self._enable_perf_diag()

        # 첫 실행 시 단축키 프리셋 다이얼로그 노출 (preset_name="" 일 때만).
        # 노출은 이벤트 루프 시작 후로 미뤄 메인 창이 먼저 보이도록 한다.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._maybe_show_hotkey_preset_dialog)

    # ---------- perf 진단 ----------
    def _enable_perf_diag(self) -> None:
        """KSTUDIO_PERF_DIAG=1 일 때만 활성. 5초마다 dump + 100ms 미세 stutter 감지.

        100Hz stutter detector: 100ms 마다 타이머 fire. 직전 fire 와 차이가 150ms +
        초과면 micro-stutter 로 기록. 5초 dump 에 worst N 개 표시.
        """
        import threading
        from ..core import perf_diag
        # micro stutter detector — 매 100ms 타이머 fire, 직전 대비 skew 측정.
        self._diag_stutter_samples: list[int] = []
        self._diag_stutter_last_ms: int = 0
        self._diag_stutter_timer = QTimer(self)
        self._diag_stutter_timer.setInterval(100)

        def _stutter_tick():
            from PySide6.QtCore import QDateTime
            now = QDateTime.currentMSecsSinceEpoch()
            if self._diag_stutter_last_ms:
                skew = (now - self._diag_stutter_last_ms) - 100
                if skew > 50:   # 50ms 초과 = micro stutter 후보.
                    self._diag_stutter_samples.append(skew)
            self._diag_stutter_last_ms = now
        self._diag_stutter_timer.timeout.connect(_stutter_tick)
        self._diag_stutter_timer.start()

        self._diag_timer = QTimer(self)
        self._diag_timer.setInterval(5000)

        def _rss_mb() -> float:
            """현재 프로세스 RSS (MB). Windows 우선, 실패 시 0.

            ctypes restype 미지정 시 64-bit pseudo-handle (-1) 이 32-bit 로 잘려
            GetProcessMemoryInfo 가 실패 → 항상 0 반환되던 버그 fix.
            """
            if sys.platform != "win32":
                return 0.0
            try:
                import ctypes
                from ctypes import wintypes
                class _PMC(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                    ]
                kernel32 = ctypes.windll.kernel32
                psapi = ctypes.windll.psapi
                kernel32.GetCurrentProcess.restype = wintypes.HANDLE
                psapi.GetProcessMemoryInfo.argtypes = [
                    wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD,
                ]
                psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
                pmc = _PMC()
                pmc.cb = ctypes.sizeof(_PMC)
                handle = kernel32.GetCurrentProcess()
                if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                    return 0.0
                return pmc.WorkingSetSize / 1024 / 1024
            except Exception:
                return 0.0

        # ffmpeg_count 는 background 스레드에서 비동기로 측정 — tasklist 가 메인
        # 스레드에서 500-1000ms block 하던 게 사용자가 보는 "잠깐잠깐 멈춤" 의 원인.
        # qimage_count 도 같은 이유 (gc.get_objects 가 수천 객체 순회 → 100-200ms).
        self._diag_async_ffmpeg_count: int = 0
        self._diag_async_qimage_count: int = 0

        def _async_measure():
            ffmpeg_n = 0
            qi_n = 0
            try:
                if sys.platform == "win32":
                    import subprocess
                    r = subprocess.run(
                        ["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe",
                         "/FO", "CSV", "/NH"],
                        capture_output=True, timeout=3,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    out = r.stdout.decode("utf-8", "replace")
                    ffmpeg_n = sum(1 for ln in out.splitlines() if "ffmpeg.exe" in ln)
            except Exception:
                pass
            try:
                import gc
                qi_n = sum(1 for o in gc.get_objects() if type(o).__name__ == "QImage")
            except Exception:
                pass
            self._diag_async_ffmpeg_count = ffmpeg_n
            self._diag_async_qimage_count = qi_n

        def _dump():
            # 직전 측정 결과 사용 (현재 측정은 새 background 작업으로 시작).
            ffmpeg_count = self._diag_async_ffmpeg_count
            qimage_count = self._diag_async_qimage_count
            counters = perf_diag.snapshot_and_reset()
            stutters = sorted(self._diag_stutter_samples, reverse=True)[:3]
            self._diag_stutter_samples.clear()
            dur_pending = 0
            thumb_pending = 0
            try:
                if hasattr(self, "_duration_probe_pool"):
                    dur_pending = self._duration_probe_pool._work_queue.qsize()
            except Exception:
                pass
            try:
                if hasattr(self, "_thumb_probe_pool"):
                    thumb_pending = self._thumb_probe_pool._work_queue.qsize()
            except Exception:
                pass
            filmstrip_jobs = len(getattr(self, "_filmstrip_jobs", {}))
            logging.warning(
                "PERF_DIAG rss=%.1fMB threads=%d ffmpeg_procs=%d qimage=%d "
                "dur_q=%d thumb_q=%d filmstrip=%d worst_stutters=%s counters=%s",
                _rss_mb(), threading.active_count(), ffmpeg_count, qimage_count,
                dur_pending, thumb_pending, filmstrip_jobs, stutters, counters,
            )
            # 다음 dump 를 위해 background 측정 트리거.
            threading.Thread(target=_async_measure, daemon=True,
                             name="PerfDiagAsync").start()

        self._diag_timer.timeout.connect(_dump)
        self._diag_timer.start()
        logging.warning("PERF_DIAG enabled — 5초 주기 로깅 시작 (RSS 기반)")

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
        # 영상 모드 전역 Space — 라이브러리 / 도크에 포커스 있어도 현재 영상 탭 재생 토글.
        # (사용자 보고: 라이브러리 클릭 후 Space 안 먹힘. 영상 모드면 항상 작동해야 함.)
        sp = QShortcut(QKeySequence(Qt.Key_Space), self)
        sp.setContext(Qt.ApplicationShortcut)
        sp.activated.connect(self._on_global_space)
        # "내 화면에 보이기" 토글 — 캡쳐 affinity + minimize 둘 다 즉시 동기화.
        self.global_toolbar.keep_visible_during_capture_changed.connect(
            self._on_keep_visible_during_capture_changed
        )
        # 초기 상태 반영 — 저장된 값으로 체크박스 상태 동기화 (시그널 발화 안 하도록 block).
        self.global_toolbar.keep_visible_chk.blockSignals(True)
        self.global_toolbar.keep_visible_chk.setChecked(
            self.app_settings.preferences.keep_visible_during_capture
        )
        self.global_toolbar.keep_visible_chk.blockSignals(False)

        # 메뉴
        self.menu_bar.new_requested.connect(self._on_file_new)
        self.menu_bar.open_requested.connect(self._on_file_open)
        self.menu_bar.new_markdown_requested.connect(self._on_new_markdown)
        self.menu_bar.save_requested.connect(self._on_file_save)
        self.menu_bar.save_as_requested.connect(self._on_file_save_as)
        self.menu_bar.export_requested.connect(self._on_export)
        self.menu_bar.export_video_requested.connect(self._on_export_video)
        self.menu_bar.export_audio_requested.connect(self._on_export_audio)
        self.menu_bar.export_subtitle_requested.connect(self._on_export_subtitle)
        self.menu_bar.open_save_folder_requested.connect(self._open_save_folder)
        self.menu_bar.quit_requested.connect(self.close)
        self.menu_bar.preferences_requested.connect(self._open_preferences)
        self.menu_bar.undo_requested.connect(self._on_undo)
        self.menu_bar.redo_requested.connect(self._on_redo)
        self.menu_bar.toggle_edit_mode_requested.connect(self._toggle_edit_mode_via_menu)
        self.menu_bar.toggle_effects_enabled_requested.connect(self._on_toggle_effects_enabled)
        self.menu_bar.gpu_acceleration_setup_requested.connect(self._on_gpu_acceleration_setup)
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
        # 이미지 생성 패널 토글 (Ctrl+Shift+G 또는 창 메뉴) — 첫 토글 시 lazy 생성.
        self.menu_bar.image_gen_visibility_toggled.connect(self._on_image_gen_visibility_toggled)
        self.menu_bar.image_gen_visibility_toggled.connect(self._on_image_gen_dock_visibility_persist)
        # 에이전트 패널 토글 (Ctrl+Shift+A 또는 창 메뉴) — 2026-05-27 추가.
        self.menu_bar.agent_panel_visibility_toggled.connect(self.agent_chat_panel.setVisible)
        self.menu_bar.agent_panel_visibility_toggled.connect(self._on_agent_panel_visibility_persist)
        # Phase 23: dock 가시성을 settings 에 영속화 — X 로 닫은 dock 이 재시작 후 다시 보이던 회귀 fix.
        self.menu_bar.library_visibility_toggled.connect(self._on_library_dock_visibility_persist)
        self.menu_bar.layers_visibility_toggled.connect(self._on_layers_dock_visibility_persist)
        self.menu_bar.record_status_visibility_toggled.connect(self._on_record_status_dock_visibility_persist)
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
        self.library_panel.entry_remove_requested.connect(self._on_library_remove)
        self.library_panel.entry_open_folder_requested.connect(self._on_library_open_folder)
        self.library_panel.entry_undelete_requested.connect(self._on_library_undelete)
        self.library_panel.files_dropped_for_library.connect(self._on_library_files_dropped)
        self.library_model.entry_renamed.connect(self._on_entry_renamed)

        # 영상 탭 프레임 → 스크린샷 단축키 (PlayerHotkeys 에서 동적으로 가져옴)
        self._snapshot_shortcut = QShortcut(self)
        self._snapshot_shortcut.setKey(
            QKeySequence(self.app_settings.player_hotkeys.snapshot or "Ctrl+Shift+P")
        )
        self._snapshot_shortcut.activated.connect(self._snapshot_current_video_frame)
        # Ctrl+C/X/A/D 는 이미지 편집 전용이지만 WindowShortcut 컨텍스트라, 켜져 있으면
        # 포커스가 마크다운 에디터·미리보기(읽기전용)·영상 타임라인에 있어도 키를 가로챈다.
        # 편집 가능한 에디터는 ShortcutOverride 를 스스로 accept 해 무사하지만, 읽기전용
        # 미리보기(QTextBrowser/WebEngine)·plain 위젯은 키를 빼앗긴다(2026-05-29 사용자 보고:
        # 문서/미리보기에서 Ctrl+C 안 됨). → EditTab 활성 시에만 켜도록 모아 토글한다.
        # 핸들러는 어차피 EditTab 없으면 no-op 이라 이미지 모드 동작은 그대로다.
        # Ctrl+C → selection 이 있으면 그 영역만, 아니면 전체 합성 이미지를 클립보드.
        # Ctrl+X → selection 영역 잘라내기 (클립보드 복사 후 ImageLayer 에서 지움).
        # Ctrl+A → 전체 선택, Ctrl+D → 선택 해제.
        # Del 처리는 LayerCanvas.keyPressEvent → EditTab.delete_selection 으로 위임
        # (WindowShortcut 으로 등록하면 LayersPanel 의 Del 을 가로채므로 제외).
        self._image_clipboard_shortcuts = [
            QShortcut(QKeySequence("Ctrl+C"), self, activated=self._copy_current_screenshot),
            QShortcut(QKeySequence("Ctrl+X"), self, activated=self._cut_current_selection),
            QShortcut(QKeySequence("Ctrl+A"), self, activated=self._on_select_all),
            QShortcut(QKeySequence("Ctrl+D"), self, activated=self._on_deselect_all),
        ]
        self._update_image_clipboard_shortcuts()

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
        # keep_visible_during_capture: KStudio UI 자체를 캡쳐에 담고 싶을 때.
        # 이전 세션에 켰었다면 exclude 적용을 건너뜀 — 안 켰으면 평소대로 exclude.
        if not self.app_settings.preferences.keep_visible_during_capture:
            if not self._self_excluded:
                self._self_excluded = exclude_from_capture(self)
        self._apply_dark_titlebar()
        # dock 레이아웃 복원을 첫 show 이후로 한 번만 — 첫 show 이전 restoreState 가
        # 일부 저장본(특히 문서 모드)에서 크래시하므로. singleShot(0) 으로 paint 직후 적용.
        if not getattr(self, "_did_initial_dock_restore", False):
            self._did_initial_dock_restore = True
            QTimer.singleShot(0, self._restore_initial_dock_layout)

    def apply_capture_visibility(self, visible_in_capture: bool) -> None:
        """keep_visible_during_capture 토글 시 즉시 affinity 동기화 — 메인 창.

        True: 캡쳐에 포함 (WDA_NONE). False: 제외 (WDA_EXCLUDEFROMCAPTURE).
        """
        if visible_in_capture:
            include_in_capture(self)
            self._self_excluded = False
        else:
            self._self_excluded = exclude_from_capture(self)

    def _on_keep_visible_during_capture_changed(self, checked: bool) -> None:
        """글로벌 툴바 토글 → settings 갱신 + affinity 즉시 반영 + 저장."""
        self.app_settings.preferences.keep_visible_during_capture = bool(checked)
        self.apply_capture_visibility(bool(checked))
        self._persist_settings()

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

    def changeEvent(self, event):  # noqa: N802 — Qt signature
        """창이 다시 활성화될 때 전역 핫키 재등록 보장 — stuck-pause 안전망.

        인라인 단축키 편집기에 포커스가 갔다가 focusOut 없이 숨겨지는 등으로 pause
        (unregister)가 resume 없이 남는 회귀(2026-05-29) 대비. 창 복귀 시 *편집 중이
        아니면* 재등록한다 — 편집 중(OneShotKeySequenceEdit 포커스)이면 키 가로채기
        방지로 건너뜀. set_bindings 는 idempotent 라 정상 상태에서 호출돼도 무해.
        """
        super().changeEvent(event)
        if event.type() != QEvent.ActivationChange or not self.isActiveWindow():
            return
        if getattr(self, "hotkeys", None) is None:
            return   # 초기화 중 (hotkeys 생성 전) 활성화 이벤트 — 무시.
        from .widgets import OneShotKeySequenceEdit
        if isinstance(QApplication.focusWidget(), OneShotKeySequenceEdit):
            return   # 단축키 지정 중 — 재등록하면 입력 키를 가로챔.
        self._reregister_hotkey()

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
            _settings_module.save(self.app_settings, _settings_module.settings_path())
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
        # "내 화면에 보이기" 토글 ON: KStudio UI 가 녹화에 담기길 원함 → 절대 숨기지 않음.
        if prefs.keep_visible_during_capture:
            return False
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
            self._mini.close_requested.connect(self._on_mini_close_requested)
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

    def _on_mini_close_requested(self):
        """MiniControl 의 X 버튼 — 사용자가 다시는 안 보고 싶음.

        녹화 자체는 계속됨 (stop 과 구분). preferences.use_mini_control = False
        로 영속화 + 디스크 저장. 다음 녹화부터 미생성. 사용자가 환경설정에서
        다시 켤 수 있음.
        """
        if self._mini is not None:
            self._mini.close()
            self._mini = None
        self.app_settings.preferences.use_mini_control = False
        self._persist_settings()

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
            self.agent_chat_panel: self.menu_bar.agent_panel_visible_action,
        })
        for dock in (self.library_dock, self.layers_dock,
                     self.record_status_dock, self.agent_chat_panel):
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
        """ffmpeg 으로 첫 프레임을 추출해 작은 썸네일 QImage 반환 (실패 시 placeholder).

        ffmpeg 가 256×256 안에 맞춘 크기로 직접 인코딩 — 이전엔 원본 해상도(1080p) PNG
        를 디스크에 쓰고 메인 스레드가 QPixmap.fromImage + scaled(SmoothTransformation)
        로 축소했음. 이제 ffmpeg 단계에서 축소되므로 메인 스레드는 작은 QImage 1번만
        다룬다 → 라이브러리 갱신 시 UI 끊김 최소.
        """
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
            no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            try:
                # -vf scale='min(256,iw)':-2 — 256 안에 맞추되 aspect 유지 (-2 = 짝수 강제).
                subprocess.run(
                    [str(self.ffmpeg_path), "-y", "-loglevel", "error",
                     "-i", str(path),
                     "-vf", "scale='min(256,iw)':-2",
                     "-frames:v", "1", str(tmp)],
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
        if entry.kind is EntryKind.DOCUMENT:
            # 문서는 디스크에서 다시 로드 (탭 텍스트는 entry 에 보관하지 않음).
            if entry.path is not None and entry.path.exists():
                self._open_markdown_path(entry.path)
            else:
                QMessageBox.warning(self, "열기 실패", "문서 파일을 찾을 수 없습니다.")
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
        # 마지막 사용 모드 영속화 — 다음 실행 시 같은 모드로 복원.
        # _persist_settings 가 _initializing 플래그를 자체적으로 체크하므로 init 중엔 no-op.
        self.app_settings.preferences.last_mode = mode.value
        self._persist_settings()
        # 모드별 테마 — 영상=현재 시안 / 이미지=mono+emerald.
        # 실제 전환일 때만 재적용 — init(prev_mode is None) 에선 main.py 의
        # 초기 apply_theme 호출이 이미 끝났으므로 중복 방지.
        if prev_mode is not None and prev_mode is not mode:
            from screen_recorder.ui.theme import apply_theme
            apply_theme(QApplication.instance(), _palette_name_for_mode(mode))
        self.global_toolbar.set_mode(mode)
        is_image = (mode is AppMode.IMAGE)
        # ToolPalette: 이미지 모드 + 창 메뉴 체크 둘 다일 때만
        tp_checked = self.menu_bar.tool_palette_visible_action.isChecked()
        self.tool_palette.setVisible(is_image and tp_checked)
        self.annotation_toolbar.setVisible(is_image)
        # 새 모드의 dock 레이아웃 복원 — 영상↔이미지 전환 시 사용자가 모드별로 떼어둔
        # 패널 배치를 그대로 유지. 단, 첫 show 이전(init) 엔 restoreState 를 미룬다 —
        # 첫 show 전 복원은 일부 저장본에서 Qt paint 크래시. 초기 복원은 showEvent 가 담당.
        if not getattr(self, "_initializing", False):
            self._restore_dock_state_for_mode(mode)
        # restoreState 후 dock 가시성을 메뉴 체크 기준으로 강제 — restoreState 가 visibility
        # 도 같이 복원해 사용자가 닫지 않은 dock 도 닫는 부작용 방지.
        self._enforce_dock_visibility()
        # 영상 모드면 레이어 패널 비활성화 (모드 무관 호출 — 안전망).
        self._apply_layers_panel_enabled_state()
        # 모드 전용 dock 의 메뉴 항목 enable/disable 갱신.
        self._apply_mode_aware_menu_enabled()
        # 이미지 편집용 Ctrl+C/X/A/D 단축키 토글 (탭 변경 없이 모드만 바뀌는 경우 대비).
        self._update_image_clipboard_shortcuts()
        # 문서 모드로 *전환* 시 WebEngine pre-warm — 이미지/영상으로 켰다가 문서로 들어온
        # 세션은 startup gate(last_mode==document)를 못 타 첫 문서 열 때 HWND 재생성으로
        # 창 전체가 깜빡이던 회귀 fix(2026-05-29). idempotent 라 startup 에 이미 했으면 no-op.
        # init 중(line 670 의 직접 호출)엔 _webengine_prewarm 속성도 startup warm 도 아직이라
        # 스킵 — 그 경로의 document 시작은 730 의 gated warm 이 담당. runtime 전환만 발동.
        if mode is AppMode.DOCUMENT and not getattr(self, "_initializing", False):
            self._maybe_prewarm_webengine(force=True)

    def _on_mode_button_clicked(self, mode: AppMode) -> None:
        """사용자가 모드 토글 버튼을 직접 클릭 — 그 모드의 가장 최근 탭으로 점프.

        주의: 모드 전환은 _open_entry 의 부수효과(currentChanged → mode_controller)
        에 의존하면 안 된다. focus_entry 가 이미 current 인 탭이면 no-op 이라 모드 시그널이
        발화되지 않아 다른 UI 들이 갱신 안 됨. 항상 명시적으로 set_mode 를 호출.

        탭 전환 정책:
        1) 그 모드의 마지막 활성 탭 (`_last_entry_per_mode`) 으로 복원 — 사용자가
           영상 시청·편집 중이었으면 시간/진행상태가 보존된 탭이 그대로 보임.
        2) 그 모드 탭이 하나라도 있지만 last 기록이 없으면 첫 탭 선택 (tab_area 의
           visibility 동기화가 자동 처리).
        3) 탭이 하나도 없으면 라이브러리의 첫 entry 로 새 탭 오픈.
        """
        self.mode_controller.set_mode(mode)
        # 1) 마지막 활성 탭 우선.
        last_eid = self._last_entry_per_mode.get(mode)
        if last_eid is not None and self.tab_area.find_index_by_entry(last_eid) >= 0:
            self.tab_area.focus_entry(last_eid)
            if mode is AppMode.VIDEO:
                self._focus_current_video_tab()
            return
        # 2) 마지막 기록은 없지만 그 모드 탭이 이미 있으면 tab_area 의 visibility
        #    동기화가 알아서 visible 한 첫 탭을 보여줌 — 추가 작업 불필요.
        target_app_mode = mode
        has_existing_tab = any(
            m is target_app_mode for _w, m, _e in self.tab_area._tabs
        )
        if has_existing_tab:
            if mode is AppMode.VIDEO:
                self._focus_current_video_tab()
            return
        # 문서 모드는 Phase 1 에서 라이브러리 백킹 entry 가 없다 — 탭이 없으면 빈 문서
        # 모드 상태만 유지하고 끝낸다 (else 분기로 빠져 스크린샷을 잘못 여는 것 방지).
        if mode is AppMode.DOCUMENT:
            return
        # 3) 그 모드 탭이 전혀 없으면 라이브러리에서 첫 entry 로 새로 오픈.
        target_kind = EntryKind.VIDEO if mode is AppMode.VIDEO else EntryKind.SCREENSHOT
        entries = self.library_model.entries(kind=target_kind)
        if entries:
            self._open_entry(entries[0].id)
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
        # 필름스트립(트림 레인 배경) 추출은 *탭이 열렸을 때만* 시작 — 시작 시 14 영상
        # 모두 duration 이 들어오면 14 ffmpeg subprocess 가 동시에 떠 OS 압박. 사용자가
        # 실제 트림 레인을 보는 시점에만 필요하므로 _hookup_video_tab_inspector 등에서
        # 명시 호출되도록 분리.
        widget = self.tab_area.tab_widget_for_entry(entry_id)
        if widget is not None and isinstance(widget, VideoTab):
            self._start_filmstrip_extraction(entry_id)

    def _on_tab_closed_by_user(self, entry_id: int) -> None:
        # 라이브러리에는 그대로 남겨둔다 (탭만 닫힘).
        # 단, Markdown 문서는 라이브러리에 없고 _markdown_paths 로만 추적하므로 닫힐 때
        # 제거해야 한다. 안 그러면 같은 파일 재오픈 시 중복-감지 루프가 사라진 탭의
        # stale eid 를 매칭해 focus_entry(없음) → 조용히 no-op 되어 재오픈이 안 됨.
        self._markdown_paths.pop(entry_id, None)

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
        # 외부 드래그/리사이즈로 효과가 바뀌면 인스펙터 spin 도 최신값으로 동기화.
        # (이거 없으면 사용자가 인스펙터 다른 필드 토글할 때 stale 한 spin 값이 다시
        # 효과에 덮어쓰이는 회귀 발생 — 줌 미리보기 체크 시 cx/cy/scale 초기화 보고)
        tab.edit_controller().sidecar_replaced.connect(
            self.inspector_panel.refresh_from_sidecar
        )
        # 전역 편집 모드 — 사용자가 어느 탭에서 토글해도 모든 영상 탭이 동시 적용.
        tab.edit_mode_change_requested.connect(self._on_global_edit_mode_change)
        # 새 탭 생성 시 현재 전역 모드를 반영.
        tab.set_edit_mode(self.app_settings.preferences.edit_mode_on)
        # 배속 일괄 켜기/끄기 — 전역 + 세션 간 영속.
        tab.speed_effects_change_requested.connect(self._on_global_speed_effects_change)
        tab.set_speed_effects_enabled(self.app_settings.preferences.speed_effects_enabled)
        # 편집 모드 컨트롤바의 출력 버튼 → 기존 export 핸들러로 라우팅.
        tab.export_requested.connect(self._on_export_video)

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

    def _on_agent_model_changed(self, model_id: str) -> None:
        """ChatPanel 의 모델 드롭다운 변경 → settings 영속화."""
        if not model_id:
            return
        try:
            self.app_settings.agent.model_id = model_id
            self._persist_settings()
        except (AttributeError, RuntimeError):
            logging.exception("agent model persist failed")

    def _on_agent_document_edit(self, action: dict, future) -> None:
        """문서 도구(worker) → UI 스레드. 활성 MarkdownTab 에 즉시 적용 (Ctrl+Z 가능) 후 future 해결.

        cursor.beginEditBlock 한 묶음으로 적용 → 사용자가 Ctrl+Z 한 번에 되돌릴 수 있음
        (setPlainText 는 undo 스택을 비워버려 사용 안 함). 영상 propose 와 달리 게이트 없이 즉시.
        """
        from PySide6.QtGui import QTextCursor
        from .markdown_tab import MarkdownTab

        def _replace_all(editor, new_text: str) -> None:
            # 작은 치환에도 cursor 가 문서 끝으로 가 뷰가 바닥으로 튀는 것 방지 —
            # 스크롤 위치를 보존(새 길이에 맞게 클램프).
            vsb = editor.verticalScrollBar()
            prev_scroll = vsb.value()
            cursor = editor.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.Document)
            cursor.removeSelectedText()
            cursor.insertText(new_text)
            cursor.endEditBlock()
            vsb.setValue(min(prev_scroll, vsb.maximum()))

        try:
            widget = self.tab_area.currentWidget()
            if not isinstance(widget, MarkdownTab):
                future.set_result({"ok": False, "error": "활성 문서 없음 — .md 를 먼저 열어주세요."})
                return
            editor = widget.editor
            op = action.get("op")
            if op == "replace":
                content = str(action.get("content", ""))
                _replace_all(editor, content)
                future.set_result({"ok": True, "op": "replace", "char_count": len(content)})
                return
            if op == "find_replace":
                find = str(action.get("find", ""))
                replace = str(action.get("replace", ""))
                count = int(action.get("count") or 0)
                if not find:
                    future.set_result({"ok": False, "error": "find 가 비어 있습니다."})
                    return
                text = editor.toPlainText()
                occurrences = text.count(find)
                if count > 0:
                    n = min(count, occurrences)
                    new_text = text.replace(find, replace, count)
                else:
                    n = occurrences
                    new_text = text.replace(find, replace)
                if n > 0:
                    _replace_all(editor, new_text)
                future.set_result({"ok": True, "op": "find_replace", "n_replaced": n})
                return
            future.set_result({"ok": False, "error": f"알 수 없는 편집 op: {op}"})
        except Exception as e:   # future 를 반드시 해결 (worker 의 await 가 영원히 안 풀리면 hang)
            logging.exception("문서 편집 적용 실패")
            try:
                future.set_result({"ok": False, "error": str(e)})
            except Exception:
                pass

    def _on_agent_whisper_download_requested(self, model_size, future) -> None:
        """Claude 의 download_whisper_model → UI 동의 카드 표시."""
        if self._pending_whisper_future is not None:
            future.set_result({
                "ok": False,
                "error": "이전 다운로드 요청 처리 중 — 그 카드를 먼저 처리하세요.",
            })
            return
        self._pending_whisper_size = model_size   # Claude 가 *제안* 한 크기.
        self._pending_whisper_future = future
        self.agent_chat_panel.append_message(AgentMessage(
            role="whisper_download_request",
            text=f"model_size={model_size}",
        ))

    def _on_whisper_card_download_clicked(self, chosen_size: str) -> None:
        """사용자가 카드 [✓ 다운로드] 클릭 → 사용자가 *드롭다운에서 고른* 크기로 실행.

        Claude 가 제안한 크기와 다를 수 있음 — 사용자 선택이 우선. 새 크기를
        settings.agent.whisper_model_size 로 영속화.
        """
        if self._pending_whisper_future is None:
            return
        future = self._pending_whisper_future
        self._pending_whisper_size = None
        self._pending_whisper_future = None
        model_size = chosen_size
        # 다음 transcribe 시 같은 크기 자동 사용하도록 설정 갱신.
        try:
            self.app_settings.agent.whisper_model_size = model_size
            self._persist_settings()
        except (AttributeError, RuntimeError):
            pass
        import threading

        def worker():
            try:
                from screen_recorder.agent.transcript import get_transcriber
                get_transcriber()._ensure_model(model_size)
                future.set_result({"ok": True, "model_size": model_size,
                                    "downloaded": True})
                # UI 측 카드 상태 갱신 — Qt slot 호출 (자동 queued).
                from PySide6.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(
                    self.agent_chat_panel, "mark_whisper_download_resolved",
                    Qt.QueuedConnection, Q_ARG(str, "done"),
                    Q_ARG(str, f"{model_size} 모델 디스크에 저장됨."),
                )
            except Exception as exc:
                logging.exception("whisper download worker failed")
                future.set_result({"ok": False, "error": str(exc)})
                from PySide6.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(
                    self.agent_chat_panel, "mark_whisper_download_resolved",
                    Qt.QueuedConnection, Q_ARG(str, "failed"),
                    Q_ARG(str, str(exc)[:200]),
                )

        threading.Thread(target=worker, daemon=True, name="whisper-download").start()

    def _on_whisper_card_cancel_clicked(self) -> None:
        """사용자가 다운로드 거절."""
        if self._pending_whisper_future is None:
            return
        future = self._pending_whisper_future
        self._pending_whisper_size = None
        self._pending_whisper_future = None
        future.set_result({"ok": False, "canceled_by_user": True})
        self.agent_chat_panel.mark_whisper_download_resolved("canceled")

    def _on_agent_show_thinking_changed(self, on: bool) -> None:
        """추론 보기 토글 → settings 영속화."""
        try:
            self.app_settings.agent.show_thinking = bool(on)
            self._persist_settings()
        except (AttributeError, RuntimeError):
            logging.exception("agent show_thinking persist failed")

    def _on_agent_proposals_apply(self, proposals, future) -> None:
        """Claude 의 apply_proposals 도구 호출 → UI 스레드 슬롯.

        2026-05-14 사용자 요청: "수락 거절 뜨는데 되돌리기 기능만 넣어주고 수락은 알아서
        하게 해줄래?" — 매번 확인 카드 띄우는 대신 *즉시 적용*. 잘못된 결과는 사용자가
        Ctrl+Z (편집 메뉴 → 실행 취소) 로 되돌림. 모든 propose 는 EditController.history
        에 push 되므로 한 번에 N 개 적용했어도 N 번 undo 로 전부 되돌릴 수 있음.

        edge case (활성 탭 없음 / 편집 모드 OFF) 는 그대로 거부 — 잘못된 상태에서 적용 시도는
        실패해야 사용자가 원인을 알 수 있음.

        남겨둔 함수들 (`_on_proposals_card_apply_clicked` / `_on_proposals_card_cancel_clicked`):
        ChatPanel 의 시그널 연결 코드가 유지되므로 그대로 두지만, 자동 적용 흐름에선 카드가
        뜨지 않아 클릭될 일 없음 — dead code 가 아니라 *unreachable until 토글 reintroduce*.
        """
        widget = self.tab_area.currentWidget()
        if not isinstance(widget, VideoTab):
            future.set_result({
                "applied": 0,
                "errors": ["활성 영상 탭 없음 — 영상을 먼저 열어주세요."],
                "queue_restored": True,
            })
            for p in proposals:
                self._proposal_queue.add(p)
            return
        if not widget.is_edit_mode_on():
            # 2026-05-19: 편집 모드 OFF 면 효과 lane 이 안 보여 사용자가 "왜 안 됐지" 혼동.
            # 자동 ON + 안내 메시지로 침묵 거부보다 친절하게. set_edit_mode 는 전역 토글
            # (모든 탭 + AppSettings 영속) — Claude 가 의도적으로 편집을 시작한 컨텍스트이므로
            # 전역 활성도 합리적 (사용자가 "필러 빼줘" 한 자체가 편집 의도 표명).
            self._on_global_edit_mode_change(True)
            self.agent_chat_panel.append_message(AgentMessage(
                role="system",
                text="ℹ 편집 모드를 자동으로 켰습니다 — 타임라인에서 효과를 확인할 수 있습니다.",
            ))
        # 즉시 적용 — 사용자 확인 카드 우회.
        result = self._apply_proposals_now(list(proposals))
        try:
            future.set_result(result)
        except Exception:
            logging.exception("apply future set_result failed")
        # 사용자 안내 메시지 — 적용된 개수 + Ctrl+Z 사용법.
        applied_n = int(result.get("applied", 0) or 0)
        errors = result.get("errors") or []
        if applied_n > 0 and not errors:
            self.agent_chat_panel.append_message(AgentMessage(
                role="system",
                text=f"✓ {applied_n}개 적용. 잘못된 결과면 Ctrl+Z 로 되돌릴 수 있습니다.",
            ))
        elif applied_n > 0 and errors:
            err_txt = "; ".join(str(e) for e in errors[:3])
            self.agent_chat_panel.append_message(AgentMessage(
                role="system",
                text=f"⚠ {applied_n}개 적용 / 일부 실패: {err_txt}. Ctrl+Z 로 되돌릴 수 있습니다.",
            ))
        elif errors:
            err_txt = "; ".join(str(e) for e in errors[:3])
            self.agent_chat_panel.append_message(AgentMessage(
                role="error",
                text=f"적용 실패: {err_txt}",
            ))

    def _on_proposals_card_apply_clicked(self) -> None:
        """사용자가 미리보기 카드의 [✓ 적용] 클릭 → 실제 적용."""
        if self._pending_apply_future is None:
            return
        proposals = self._pending_apply_proposals
        future = self._pending_apply_future
        self._pending_apply_proposals = []
        self._pending_apply_future = None
        result = self._apply_proposals_now(proposals)
        try:
            future.set_result(result)
        except Exception:
            logging.exception("apply future set_result failed")
        self.agent_chat_panel.mark_proposals_resolved("applied")

    def _on_proposals_card_cancel_clicked(self) -> None:
        """사용자가 미리보기 카드의 [✗ 취소] 클릭 → 적용 안 함."""
        if self._pending_apply_future is None:
            return
        proposals = self._pending_apply_proposals
        future = self._pending_apply_future
        self._pending_apply_proposals = []
        self._pending_apply_future = None
        # 큐 복원 — 사용자가 다시 시도 가능.
        for p in proposals:
            self._proposal_queue.add(p)
        try:
            future.set_result({
                "applied": 0,
                "canceled_by_user": True,
                "queue_restored": True,
                "note": "사용자가 적용 취소. 제안은 큐에 다시 복원됨.",
            })
        except Exception:
            logging.exception("apply future set_result failed")
        self.agent_chat_panel.mark_proposals_resolved("canceled")

    def append_autoedit_system_message(self, n_effects: int, failed: list[str]) -> None:
        """자동편집 완료 시 사용자 안내. 채팅 패널에 시스템 메시지로 출력."""
        if not hasattr(self, "agent_chat_panel"):
            return
        msg = f"✓ 자동편집 완료. {n_effects}개 효과 추가. Ctrl+Z 로 되돌릴 수 있습니다."
        if failed:
            msg += f" (실패한 분석기: {', '.join(failed)})"
        from screen_recorder.agent.runtime import AgentMessage
        self.agent_chat_panel.append_message(AgentMessage(role="system", text=msg))

    def _apply_proposals_now(self, proposals) -> dict:
        """실제 sidecar mutation 실행 (UI 스레드).

        action 별 디스패치:
        - "add"    → ec.add_effect(build_effect_from_proposal(p))
        - "remove" → ec.remove_effect(effect_id)
        - "modify" → 기존 효과를 dataclasses.replace 로 부분 갱신 후 ec.update_effect

        같은 배치 안에서 add → modify/remove 가 같은 proposal 을 가리킬 때 자동 remap:
        Claude 가 prop_ABC 로 add 한 직후 modify(effect_id='prop_ABC') 호출 가능. add 가
        실제로 만든 effect.id 와 prop_ABC 가 다르므로 (uuid 기반) 그대로 두면 'not found'.
        proposal_id → real_effect_id 매핑을 한 배치 안에서 유지해 remap.
        """
        from dataclasses import replace
        from screen_recorder.agent.proposals import (
            apply_modify_overrides, build_effect_from_proposal,
        )
        widget = self.tab_area.currentWidget()
        if not isinstance(widget, VideoTab):
            return {"applied": 0, "errors": ["활성 영상 탭 없음"]}
        ec = widget.edit_controller()
        applied: list[dict] = []
        errors: list[str] = []
        # 배치 내 proposal_id → 실제 effect.id 매핑. add 가 성공하면 등록.
        # modify/remove 가 이전 add 의 proposal_id 를 effect_id 로 보내면 remap.
        proposal_to_real: dict[str, str] = {}
        for p in proposals:
            action = getattr(p, "action", "add")
            try:
                if action == "add":
                    eff = build_effect_from_proposal(p)
                    ok = ec.add_effect(eff)
                    if ok:
                        proposal_to_real[p.id] = eff.id
                        applied.append({"action": "add", "id": eff.id, "type": p.type, "proposal_id": p.id})
                    else:
                        errors.append(f"{p.id} (add {p.type}): rejected")
                elif action == "remove":
                    eid_raw = str(p.payload.get("effect_id", ""))
                    eid = proposal_to_real.get(eid_raw, eid_raw)
                    ok = ec.remove_effect(eid)
                    if ok:
                        applied.append({"action": "remove", "effect_id": eid, "proposal_id": p.id})
                    else:
                        errors.append(f"{p.id} (remove): effect_id '{eid}' not found")
                elif action == "modify":
                    # 매번 최신 sidecar 를 다시 가져옴 — 직전 add 가 새 효과를 추가했을 수 있음.
                    sc = widget.sidecar()
                    eid_raw = str(p.payload.get("effect_id", ""))
                    eid = proposal_to_real.get(eid_raw, eid_raw)
                    target = next((e for e in sc.effects if e.id == eid), None) if sc else None
                    if target is None:
                        errors.append(f"{p.id} (modify): effect_id '{eid_raw}' not found")
                        continue
                    overrides = {k: v for k, v in p.payload.items() if k != "effect_id"}
                    # nested dict (예: caption.font={"family":"...", "size":48}) 는 그대로
                    # replace 하면 *dataclass 자리에 dict* 가 들어가 paintEvent 등에서
                    # AttributeError. asdict→merge→_effect_from_dict 로 정상 coerce.
                    try:
                        new_eff = apply_modify_overrides(target, overrides)
                    except (TypeError, ValueError, KeyError) as exc:
                        errors.append(f"{p.id} (modify {eid}): invalid field — {exc}")
                        continue
                    ok = ec.update_effect(new_eff)
                    if ok:
                        applied.append({"action": "modify", "effect_id": eid, "proposal_id": p.id,
                                        "fields_changed": list(overrides.keys())})
                    else:
                        errors.append(f"{p.id} (modify {eid}): rejected (time overlap?)")
                else:
                    errors.append(f"{p.id}: unknown action {action!r}")
            except Exception as exc:
                logging.exception("agent apply: action=%s proposal=%s failed", action, p.id)
                errors.append(f"{p.id} ({action}): {exc}")
        return {
            "applied": len(applied),
            "applied_details": applied,
            "errors": errors,
            "queue_restored": False,
        }

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

    def _on_library_remove(self, entry_id: int) -> None:
        """Del — 라이브러리 목록에서만 제외 (디스크 파일은 그대로). 열려 있던 탭은 닫음.

        Shift+Del 의 _on_library_delete 와 달리 send2trash 호출 X. Ctrl+Z 복원 시 디스크
        파일이 이미 있으므로 그대로 다시 라이브러리에 add 하면 됨.
        """
        entry = self.library_model.get(entry_id)
        if entry is None:
            return
        snapshot = self._snapshot_entry(entry)
        snapshot["trashed"] = False
        self._close_tab_and_release_handles(entry_id)
        self.library_model.remove(entry_id)
        self._push_undelete_snapshot(snapshot)

    def _snapshot_entry(self, entry) -> dict:
        """Del/Shift+Del 공통 — undelete stack 용 entry 스냅샷."""
        return {
            "kind": entry.kind,
            "thumbnail": entry.thumbnail,
            "source_label": entry.source_label,
            "display_name": entry.display_name,
            "path": entry.path,
            "duration_ms": entry.duration_ms,
            "origin": entry.origin,
        }

    def _push_undelete_snapshot(self, snapshot: dict) -> None:
        self._undelete_stack.append(snapshot)
        if len(self._undelete_stack) > 8:
            self._undelete_stack.pop(0)

    def _close_tab_and_release_handles(self, entry_id: int) -> None:
        """엔트리에 연결된 탭이 있으면 닫고, 영상/GIF 핸들을 해제한 뒤 이벤트 루프를 굴린다.

        Shift+Del 에서 send2trash 가 sharing violation 안 나도록 핸들 해제가 필요.
        Del(라이브러리에서만 제외) 도 같은 절차를 거쳐 일관성 유지 — 어차피 탭은 닫혀야.
        """
        idx = self.tab_area.find_index_by_entry(entry_id)
        widget = self.tab_area.tab_widget_for_entry(entry_id)
        if isinstance(widget, VideoTab):
            try:
                widget.player.stop()
                widget.player.release_file_handles()
            except (RuntimeError, AttributeError):
                pass
        if idx >= 0:
            self.tab_area._on_close_requested(idx)
        from PySide6.QtCore import QCoreApplication, QEvent
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QApplication.processEvents()

    def _on_library_delete(self, entry_id: int) -> None:
        entry = self.library_model.get(entry_id)
        if entry is None:
            return
        # 라이브러리에서 먼저 제거 — 사용자에게 즉각적인 UI 피드백을 주기 위함.
        # send2trash 와 영상 탭 close 는 Windows 에서 수백 ms 걸릴 수 있는데, 그 동안
        # 라이브러리에 항목이 남아 있으면 "Del 안 먹은 듯" 한 인상을 줌.
        path = entry.path
        kind = entry.kind
        snapshot = self._snapshot_entry(entry)

        self._close_tab_and_release_handles(entry_id)
        self.library_model.remove(entry_id)

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
        if trashed_ok:
            snapshot["trashed"] = True
            self._push_undelete_snapshot(snapshot)

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
        """라이브러리에서 Ctrl+Z — 마지막으로 제외/삭제한 항목을 되돌린다.

        - trashed=True 스냅샷: 휴지통에서 복원 후 라이브러리에 재등록.
        - trashed=False 스냅샷: 디스크 파일은 그대로이므로 라이브러리에만 재등록.
        - path=None (미저장 항목): 라이브러리에만 재등록.
        """
        if not self._undelete_stack:
            return
        snapshot = self._undelete_stack[-1]
        path = snapshot.get("path")
        trashed = snapshot.get("trashed", True)   # 구버전 스냅샷 호환 — 휴지통이라 가정.

        if path is not None and trashed:
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
        """영상 탭에서 '현재 프레임 → 스크린샷' 요청.

        screenshot 캡처와 동일하게 display_name 을 미리 만들어 라이브러리/탭 라벨이
        실제 저장될 파일명으로 즉시 보이도록 한다 (사용자 요청: "영상에서 나오면 이름은
        바로 바꿔줘야지"). label_at ('region @ 01:23.4') 은 `:` / `@` 가 들어가 그대로
        쓰면 사용자가 "파일이름이 이상하다" 고 느낌 + 사용자 패턴에 {target} 포함 시
        Windows 파일명으로 부적합 → target 으로는 `:` / `@` 를 `_` 로 치환한 안전판 사용.
        """
        safe_target = label_at.replace(":", "_").replace("@", "_").replace(" ", "_").strip("_")
        display = self._build_screenshot_display_name(safe_target)
        entry = self.library_model.add(
            EntryKind.SCREENSHOT, thumbnail=image, source_label=label_at,
            display_name=display,
        )
        self.tab_area.add_screenshot(image=image, source_label=label_at, entry_id=entry.id,
                                      display_name=display)

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
        elif action_id == "image_gen":
            # 2026-05-27: 도구 팔레트에서 진입 → 메뉴 체크 토글 (lazy 생성 + show + persist).
            self.menu_bar.image_gen_visible_action.setChecked(True)

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
        # 영상 탭이면 EditController 의 자체 History 로 라우팅.
        # menu_bar.undo_action (WindowShortcut) 이 VideoTab.keyPressEvent 보다 먼저
        # 잡아버려, 분기를 안 두면 영상 자르기/삭제가 Ctrl+Z 로 복구되지 않는다.
        cur = self.tab_area.currentWidget()
        if isinstance(cur, VideoTab):
            if cur._edit_controller.undo():
                cur.player.flash_action("↶ 되돌리기")
            return
        tab = self._current_screenshot_tab()
        if tab:
            tab.undo_stack.undo()

    def _on_redo(self) -> None:
        cur = self.tab_area.currentWidget()
        if isinstance(cur, VideoTab):
            if cur._edit_controller.redo():
                cur.player.flash_action("↷ 다시 실행")
            return
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
    MARKDOWN_EXTS = {".md", ".markdown"}

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
        """파일 → 열기. .kstudio (이미지 zip 또는 영상 사이드카 JSON, magic 으로 분기) /
        일반 raster / 영상 모두 지원."""
        # 최근 열기 폴더 기억 — settings.preferences.last_open_dir.
        initial = (self.app_settings.preferences.last_open_dir or "").strip()
        path, _ = QFileDialog.getOpenFileName(
            self, "파일 열기", initial,
            "지원 파일 (*.kstudio *.png *.jpg *.jpeg *.webp *.bmp "
            "*.mp4 *.gif *.webm *.mov *.avi *.mkv *.md *.markdown);;모든 파일 (*.*)",
        )
        if not path:
            return
        p = Path(path)
        # 선택 후 그 폴더를 다음 열기의 시작점으로.
        self.app_settings.preferences.last_open_dir = str(p.parent)
        try:
            self._persist_settings()
        except (RuntimeError, OSError):
            pass
        self._open_path(p)

    def _on_library_files_dropped(self, paths: list) -> None:
        """라이브러리 패널에 외부 파일 드롭 → 라이브러리에만 추가 (탭 자동 열림 X).

        이미 라이브러리에 있는 파일은 건너뜀. 추가된 entry 의 썸네일/duration 은
        백그라운드 probe 로 채워짐 (탭 열 때와 동일 흐름).
        """
        added = 0
        for path_str in paths:
            try:
                p = Path(str(path_str))
            except (TypeError, ValueError):
                continue
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if self._find_library_entry_for_path(p) is not None:
                continue   # 중복 — 라이브러리에 이미 있음
            if ext in self.VIDEO_EXTS:
                placeholder = QImage(64, 36, QImage.Format_ARGB32)
                placeholder.fill(0xFF222222)
                entry = self.library_model.add(
                    EntryKind.VIDEO,
                    thumbnail=placeholder,
                    source_label="dropped",
                    display_name=p.name,
                    path=p,
                    duration_ms=0,
                    origin="opened",
                )
                self._probe_duration_async(p, entry.id)
                self._extract_thumbnail_async(p, entry.id)
                added += 1
            elif ext in self.IMAGE_EXTS:
                try:
                    img = QImage(str(p))
                    if img.isNull():
                        continue
                except (OSError, ValueError):
                    continue
                self.library_model.add(
                    EntryKind.SCREENSHOT,
                    thumbnail=img,
                    source_label="dropped",
                    display_name=p.name,
                    path=p,
                    duration_ms=0,
                    origin="opened",
                )
                added += 1
            elif ext in self.MARKDOWN_EXTS:
                self.library_model.add(
                    EntryKind.DOCUMENT,
                    thumbnail=QImage(),       # 문서는 썸네일 없음 (📄 라벨로 구분)
                    source_label="dropped",
                    display_name=p.name,
                    path=p,
                    origin="opened",
                )
                added += 1
        # 라이브러리 dock 가 숨겨져 있으면 사용자가 결과를 못 봄 → 보여주기.
        if added > 0 and not self.library_dock.isVisible():
            self.library_dock.show()

    def _open_path(self, p: Path) -> None:
        """확장자 기준 분기 + .kstudio 는 magic 으로 zip(이미지)/JSON(영상 사이드카) 구분."""
        ext = p.suffix.lower()
        if ext == ".kstudio":
            # 이미지 편집기 zip 또는 영상 사이드카 JSON — magic 으로 분기.
            if self._is_video_sidecar_json(p):
                self._open_sidecar_path(p)
                return
            self._open_image_path(p)
            return
        if ext in self.IMAGE_EXTS:
            self._open_image_path(p)
        elif ext in self.VIDEO_EXTS:
            self._open_video_path(p)
        elif ext in self.MARKDOWN_EXTS:
            self._open_markdown_path(p)
        else:
            QMessageBox.warning(
                self, "지원하지 않는 파일",
                f"지원하지 않는 형식입니다: {p.suffix}",
            )

    @staticmethod
    def _is_video_sidecar_json(p: Path) -> bool:
        """파일 첫 바이트로 영상 사이드카 JSON 인지 판정 (zip 'PK' 시그니처 아님)."""
        try:
            with open(p, "rb") as f:
                head = f.read(4).lstrip()
            return bool(head) and head[:1] == b"{"
        except OSError:
            return False

    def _open_sidecar_path(self, p: Path) -> None:
        """사이드카(.kstudio JSON) 파일을 열어 source_path 의 영상을 영상 탭으로.

        사이드카 파일 자체를 EditController 에 명시 전달 — hash 매칭 우회. 라이브러리에
        같은 영상이 이미 있으면 entry 중복 추가 없이 그 entry 재사용.
        """
        from ..effects.sidecar import load as load_sidecar
        try:
            sc = load_sidecar(p)
        except Exception as e:
            QMessageBox.warning(self, "편집본 열기 실패",
                                  f"사이드카 파일을 읽을 수 없습니다:\n{e}")
            return
        src = Path(sc.source_path or "")
        if not sc.source_path or not src.exists():
            QMessageBox.warning(
                self, "원본 영상 없음",
                "사이드카가 가리키는 원본 영상 파일을 찾을 수 없습니다:\n"
                f"{sc.source_path or '(경로 없음)'}\n\n"
                "영상을 원래 경로로 옮긴 후 다시 시도하거나, 영상을 직접 열어주세요.",
            )
            return
        self._open_video_path(src, sidecar_dir_override=p.parent, sidecar_path=p)

    def _find_library_entry_for_path(self, path: Path):
        """라이브러리에서 같은 file path 의 entry 찾기. 없으면 None."""
        try:
            target = path.resolve()
        except OSError:
            target = path
        for entry in self.library_model.entries():
            ep = getattr(entry, "path", None)
            if ep is None:
                continue
            try:
                if Path(ep).resolve() == target:
                    return entry
            except OSError:
                continue
        return None

    # ---------- 이미지 생성 별창 (Ctrl+Shift+G / 도구 팔레트 — 2026-05-27 dialog 로 변경) ----------
    def _on_image_gen_visibility_toggled(self, visible: bool) -> None:
        """창 메뉴 / Ctrl+Shift+G / 도구 팔레트 아이콘 진입점.

        첫 토글 시 lazy 생성. 비모달 별창이라 떠있는 동안 메인 도구 자유 사용.
        """
        if visible:
            if self.image_gen_dialog is None:
                from .image_gen import ImageGenDialog
                self.image_gen_dialog = ImageGenDialog(parent=self)
                self.image_gen_dialog.image_for_editor.connect(
                    self._open_image_path_from_generated
                )
                # video_btn 은 Phase 6+ 까지 비활성 — image_for_video 신호는 와이어링만.
                self.image_gen_dialog.image_for_video.connect(
                    self._on_generated_image_for_video
                )
                # X 로 닫음 → 메뉴 체크 자동 해제 (settings 영속도 따라옴).
                self.image_gen_dialog.closed.connect(
                    lambda: self.menu_bar.image_gen_visible_action.setChecked(False)
                )
            self.image_gen_dialog.show()
            self.image_gen_dialog.raise_()
            self.image_gen_dialog.activateWindow()
        elif self.image_gen_dialog is not None:
            self.image_gen_dialog.hide()

    def _open_image_path_from_generated(self, path_str: str) -> None:
        """ImageGenDock 의 '편집기로 열기' — 생성한 PNG 를 새 EditTab 으로 연다."""
        self._open_image_path(Path(path_str))

    def _on_generated_image_for_video(self, path_str: str) -> None:
        """ImageGenDock 의 '영상에 추가' placeholder — 현재는 비활성 버튼이라 호출 안 됨."""
        QMessageBox.information(
            self,
            "영상에 추가",
            "다음 업데이트에서 지원 예정. 현재는 '편집기로 열기' 또는 '저장' 만 사용 가능합니다.",
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

    # ---------- Markdown 문서 ----------
    def _open_markdown_path(self, p: Path) -> None:
        """.md/.markdown 파일을 새 MarkdownTab 으로 연다 (이미 열려 있으면 포커스).

        라이브러리에 같은 path 의 DOCUMENT entry 가 있으면 재사용(중복 추가 방지),
        없으면 새 entry 등록 — 영상/이미지 '열기'처럼 문서도 라이브러리에 남는다.
        """
        from .markdown_tab import MarkdownTab
        # 이미 열린 같은 문서면 그 탭으로 포커스 (중복 생성 방지).
        for eid, path in self._markdown_paths.items():
            try:
                same = Path(path).resolve() == p.resolve()
            except OSError:
                same = path == p
            if same:
                self.tab_area.focus_entry(eid)
                self.mode_controller.set_mode(AppMode.DOCUMENT)
                return
        try:
            md = self.app_settings.markdown
            tab = MarkdownTab.from_file(
                p, editor_font_pt=md.editor_font_pt, preview_zoom=md.preview_zoom
            )
        except OSError as e:
            QMessageBox.warning(self, "열기 실패", str(e))
            return
        self._wire_markdown_tab(tab)
        existing = self._find_library_entry_for_path(p)
        if existing is not None:
            entry_id = existing.id
        else:
            entry = self.library_model.add(
                EntryKind.DOCUMENT, thumbnail=QImage(),
                source_label="opened", display_name=p.name, path=p, origin="opened",
            )
            entry_id = entry.id
        self._markdown_paths[entry_id] = p
        self.tab_area.add_markdown(tab, entry_id=entry_id, display_name=p.name)
        self.mode_controller.set_mode(AppMode.DOCUMENT)

    def _ensure_markdown_library_entry(self, entry_id: int, path: Path) -> None:
        """문서 저장 후 라이브러리 동기화 — blank(next_id) 문서면 같은 id 로 등록(승격),
        이미 있으면 path/이름만 갱신. 저장된 문서가 라이브러리에 나타나게 한다."""
        existing = self.library_model.get(entry_id)
        if existing is None:
            self.library_model.add_with_id(
                entry_id, EntryKind.DOCUMENT, thumbnail=QImage(),
                source_label="saved", display_name=path.name, path=path, origin="opened",
            )
        elif existing.path != path or existing.display_name != path.name:
            existing.path = path
            existing.display_name = path.name
            self.library_model.entry_renamed.emit(entry_id, path.name)

    def _on_new_markdown(self) -> None:
        """파일 → 새 Markdown 문서 (Ctrl+Shift+M). 빈 문서 탭 생성."""
        from .markdown_tab import MarkdownTab
        md = self.app_settings.markdown
        tab = MarkdownTab.from_blank(
            editor_font_pt=md.editor_font_pt, preview_zoom=md.preview_zoom
        )
        self._wire_markdown_tab(tab)
        entry_id = self.library_model.next_id()
        self.tab_area.add_markdown(tab, entry_id=entry_id, display_name="untitled.md")
        self.mode_controller.set_mode(AppMode.DOCUMENT)

    def _wire_markdown_tab(self, tab) -> None:
        """새 MarkdownTab 의 폰트 변경을 settings 영속에 연결."""
        tab.font_settings_changed.connect(self._on_markdown_font_changed)

    def _on_markdown_font_changed(self, editor_pt: int, preview_zoom: float) -> None:
        """문서 폰트 크기 변경 → 메모리 즉시 반영, 디스크 쓰기는 디바운스(400ms).

        Ctrl+휠은 한 번 굴릴 때 이벤트가 연속으로 와서 매번 settings.json 전체를
        재직렬화/기록하면 _persist_settings 의 '자주 안 바뀌는 설정만' 계약을 어긴다.
        """
        self.app_settings.markdown.editor_font_pt = int(editor_pt)
        self.app_settings.markdown.preview_zoom = float(preview_zoom)
        timer = getattr(self, "_markdown_font_persist_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(400)
            timer.timeout.connect(self._persist_settings)
            self._markdown_font_persist_timer = timer
        timer.start()

    # ---------- 드래그 앤 드롭 (외부 파일 → 탭) ----------
    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        md = e.mimeData()
        if md.hasUrls():
            for u in md.urls():
                ext = Path(u.toLocalFile()).suffix.lower()
                if ext in self.IMAGE_EXTS or ext in self.VIDEO_EXTS \
                        or ext in self.MARKDOWN_EXTS:
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
            if ext in self.IMAGE_EXTS or ext in self.VIDEO_EXTS \
                    or ext in self.MARKDOWN_EXTS:
                self._open_path(p)
                opened += 1
        if opened > 0:
            e.acceptProposedAction()
        else:
            super().dropEvent(e)

    def _open_video_path(self, p: Path, sidecar_dir_override: "Path | None" = None,
                          sidecar_path: "Path | None" = None) -> None:
        """영상 파일을 새 VideoTab 으로 연다.

        sidecar_dir_override / sidecar_path 가 주어지면 EditController 에 명시 전달.
        라이브러리에 같은 path 의 entry 가 이미 있으면 중복 추가 없이 재사용 (Phase 19.5
        사용자 보고: 사이드카 열 때마다 같은 영상이 라이브러리에 또 추가되는 회귀).
        """
        existing = self._find_library_entry_for_path(p)
        if existing is not None:
            entry_id = existing.id
        else:
            placeholder = QImage(64, 36, QImage.Format_ARGB32)
            placeholder.fill(0xFF222222)
            entry = self.library_model.add(
                EntryKind.VIDEO,
                thumbnail=placeholder,
                source_label="opened",
                display_name=p.name,
                path=p,
                duration_ms=0,
                origin="opened",
            )
            entry_id = entry.id
            # 라이브러리 썸네일 + duration 백그라운드 추출. 탭이 열려 player 가
            # 정확한 duration 을 emit 하기 전까지 (또는 탭을 안 여는 .kstudio 사이드카
            # 흐름) 라이브러리에 0s 로 남아 있는 회귀 방지. 시간/썸네일 분리 — 시간
            # 풀이 더 빠르게 응답.
            self._probe_duration_async(p, entry_id)
            self._extract_thumbnail_async(p, entry_id)
        self.tab_area.add_video(
            path=p, source_label="opened",
            duration_ms=0, entry_id=entry_id,
            sidecar_dir=sidecar_dir_override,
            sidecar_path=sidecar_path,
        )
        self.mode_controller.set_mode(AppMode.VIDEO)
        self._restore_window_for_capture()

    def _resolve_sidecar_dir(self) -> "Path":
        """사이드카(.kvedit) 저장 폴더 결정.

        - preferences.sidecar_dir 가 지정돼 있으면 그 경로 사용.
        - 비어 있으면(기본) **영상 저장 폴더 아래 `sidecars`** (사용자 요청 2026-05-29:
          %APPDATA% 대신 영상 옆에 두기). 생성 실패 시 OS 기본(default_sidecar_dir)로 폴백.
        """
        from ..effects import default_sidecar_dir
        custom = (self.app_settings.preferences.sidecar_dir or "").strip()
        if custom:
            p = Path(custom)
            try:
                p.mkdir(parents=True, exist_ok=True)
                return p
            except OSError:
                pass   # 사용자 경로 생성 실패 → 아래 기본 경로로 폴백
        video_dir = self.app_settings.general.output_dir or str(default_video_dir())
        p = Path(video_dir) / "sidecars"
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except OSError:
            return default_sidecar_dir()

    def _on_file_save(self) -> None:
        """현재 편집 탭을 저장.

        - 영상 탭이면 사이드카(.kstudio) 즉시 저장 — 사용자 멘탈모델 "Ctrl+S = 작업 저장"
          에 맞춰 mp4 export 가 아닌 사이드카 flush. mp4 출력은 Ctrl+Shift+E /
          편집 모드의 📤 출력 버튼 / 메뉴로만 (Phase 19.5 hotfix).
        - 이미지(스크린샷) 탭이면 기존 자동 저장 흐름.
        """
        # Markdown 문서 탭 — UTF-8 로 저장 (blank 면 Save As 다이얼로그).
        from .markdown_tab import MarkdownTab, SaveResult
        md = self.tab_area.currentWidget()
        if isinstance(md, MarkdownTab):
            had_path = md.saved_path() is not None
            result = md.save()
            if result is SaveResult.SAVED:
                sp = md.saved_path()
                if not had_path and sp is not None:   # blank→Save As 로 새 경로 생김
                    eid = self.tab_area.entry_id_for_widget(md)
                    if eid is not None:
                        self._markdown_paths[eid] = sp
                        self.tab_area.update_tab_base(eid, sp.name)
                        self._ensure_markdown_library_entry(eid, sp)
            elif result is SaveResult.FAILED:
                QMessageBox.warning(self, "저장 실패",
                                    "문서를 저장하지 못했습니다. 경로/권한을 확인하세요.")
            # SaveResult.CANCELLED → 조용히 통과.
            return
        # 영상 탭 — 사이드카 즉시 저장. 변경 없어도 무조건 디스크 write (사용자
        # 멘탈모델 "Ctrl+S = 저장" — autosave 디바운스 종료 후에도 동일 메시지).
        cur = self.tab_area.current_video_tab()
        if cur is not None:
            try:
                ok = cur._edit_controller.save_now()
            except (RuntimeError, AttributeError):
                ok = False
            try:
                if ok:
                    cur.player.flash_action("💾 사이드카 저장됨")
                else:
                    cur.player.flash_action("⚠ 저장 실패")
            except (RuntimeError, AttributeError):
                pass
            return
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
        """현재 편집 탭을 다른 이름으로 저장. PNG 가 기본, .kstudio/JPG/WebP/BMP 도 선택 가능.

        영상 탭은 export 다이얼로그로 (편집 결과를 새 mp4 로 저장).
        """
        from .markdown_tab import MarkdownTab, SaveResult
        md = self.tab_area.currentWidget()
        if isinstance(md, MarkdownTab):
            result = md.save_as()
            if result is SaveResult.FAILED:
                QMessageBox.warning(self, "저장 실패",
                                    "문서를 저장하지 못했습니다. 경로/권한을 확인하세요.")
                return
            if result is SaveResult.SAVED:
                # 성공 시에만 _markdown_paths 갱신 + 탭 라벨 동기화 (중복 열기 감지용).
                sp = md.saved_path()
                if sp is not None:
                    eid = self.tab_area.entry_id_for_widget(md)
                    if eid is not None:
                        self._markdown_paths[eid] = sp
                        self.tab_area.update_tab_base(eid, sp.name)
                        self._ensure_markdown_library_entry(eid, sp)
            # SaveResult.CANCELLED → 조용히 통과 (경고 없음).
            return
        if self.tab_area.current_video_tab() is not None:
            self._on_export_video()
            return
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

    def _on_global_space(self) -> None:
        """영상 모드 전역 Space — 라이브러리/도크에 포커스 있어도 영상 탭 재생 토글.

        텍스트 입력 위젯에 포커스가 있으면 (캡션 인스펙터 등) 무시해 텍스트 입력 보호.
        """
        from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit, QPlainTextEdit
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtGui import QKeyEvent
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit)):
            # 입력 위젯 포커스 — Space 가 텍스트로 들어가야 함. 여기서 가로채면 안 됨.
            # 직접 KeyEvent 를 forward.
            ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " ")
            QCoreApplication.sendEvent(focus, ev)
            return
        if self.mode_controller.mode() != AppMode.VIDEO:
            return
        tab = self.tab_area.current_video_tab() if hasattr(
            self.tab_area, "current_video_tab"
        ) else None
        if tab is None:
            return
        try:
            tab.player.toggle_play()
        except (RuntimeError, AttributeError):
            pass

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

        # Export 해상도 = 실제 영상 해상도 (ffprobe). player 위젯 크기를 쓰면
        # 편집창 크기에 따라 surface 가 source aspect 와 어긋나 'stretch' 시 영상이
        # 위아래로 늘어남. 다중 segment 트랙은 video_track[0].src, 단일이면 src_path.
        # ffprobe 실패 시 player 위젯 크기로 폴백.
        from ..services.media_probe import probe_video_size
        if len(sidecar.video_track) >= 1:
            primary_src = sidecar.video_track[0].src
        else:
            primary_src = str(src_path)
        pw, ph = probe_video_size(primary_src)
        if pw > 0 and ph > 0:
            surface_w, surface_h = pw, ph
        else:
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

        from .export_dialog import ExportProgressOverlay
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

        # 오른쪽 하단 미니 진행 위젯 — 비모달이라 편집 계속 가능.
        overlay = ExportProgressOverlay(self)
        job.progress.connect(overlay.set_progress)
        job.finished.connect(overlay.set_finished)
        job.error.connect(overlay.set_error)
        overlay.cancel_clicked.connect(job.cancel)
        overlay.cancel_clicked.connect(dialog.close)
        overlay.show_export()
        self._export_overlay = overlay   # GC 방지

        job.start()
        dialog.show()

    def _on_export_audio(self) -> None:
        """현재 활성 영상 탭의 음성만 추출 — MP3/WAV + 채널/샘플링 설정 (2026-05-20).

        흐름:
        1. 활성 영상 탭 확인
        2. AudioExportSettingsDialog 로 형식·채널·샘플링·비트레이트 입력
        3. QFileDialog 로 저장 경로 — 확장자는 형식에 따라 자동
        4. build_audio_export_args 로 ffmpeg argv 생성 (cut 적용)
        5. ExportJob 으로 백그라운드 실행 + ExportDialog 진행 표시
        """
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from .audio_export_dialog import AudioExportSettingsDialog
        from .export_dialog import ExportDialog, ExportProgressOverlay
        from ..encode.audio_export import (
            build_audio_export_args, compute_audio_keep_intervals,
        )
        from ..encode.export_job import ExportJob

        tab = self.tab_area.current_video_tab() if hasattr(self.tab_area, "current_video_tab") else None
        if tab is None:
            return
        sidecar = tab._edit_controller.sidecar()
        src_path = tab._source_path
        main_duration = tab.player.duration_ms()
        if main_duration <= 0:
            QMessageBox.warning(self, "음성 내보내기", "영상 길이가 확정되지 않았습니다.")
            return

        # 1) 사이드카 → keep 구간 (cut 적용).
        try:
            audio_src, keep = compute_audio_keep_intervals(sidecar)
        except (ValueError, NotImplementedError) as e:
            QMessageBox.warning(self, "음성 내보내기", str(e))
            return
        # 결과 총 길이 — progress 분모.
        total_ms = sum(e - s for s, e in keep)
        if total_ms <= 0:
            QMessageBox.warning(
                self, "음성 내보내기",
                "남는 음성 구간이 없습니다 (모든 구간이 cut 처리됨).",
            )
            return

        # 2) 설정 다이얼로그.
        settings_dlg = AudioExportSettingsDialog(parent=self)
        if settings_dlg.exec() != QDialog.Accepted:
            return
        settings = settings_dlg.current_settings()
        ext = settings_dlg.suggested_extension()

        # 3) 저장 경로 — 기본은 원본 폴더의 _audio.{ext}.
        default = Path(src_path).with_name(Path(src_path).stem + "_audio" + ext)
        filter_label = "MP3 (*.mp3)" if ext == ".mp3" else "WAV (*.wav)"
        dst, _ = QFileDialog.getSaveFileName(
            self, "음성 파일 저장", str(default), filter_label,
        )
        if not dst:
            return
        dst = Path(dst)

        # 4) ffmpeg argv.
        argv = build_audio_export_args(
            src_path=str(audio_src), keep_intervals=keep,
            settings=settings, dst_path=str(dst),
            ffmpeg_path=str(self.ffmpeg_path),
        )

        # 5) 백그라운드 실행 + 진행 표시 (영상 export 와 동일 패턴).
        dialog = ExportDialog(total_duration_ms=total_ms, parent=self)
        dialog.setWindowTitle("음성 내보내기")
        job = ExportJob(
            ffmpeg_path=self.ffmpeg_path,
            argv=argv, png_paths=[], dst_path=dst,
            total_duration_ms=total_ms,
        )
        job.progress.connect(dialog.set_progress)
        job.finished.connect(dialog.set_finished)
        job.error.connect(dialog.set_error)
        dialog.cancel_requested.connect(job.cancel)
        dialog.open_folder_requested.connect(self._open_in_explorer)

        overlay = ExportProgressOverlay(self)
        job.progress.connect(overlay.set_progress)
        job.finished.connect(overlay.set_finished)
        job.error.connect(overlay.set_error)
        overlay.cancel_clicked.connect(job.cancel)
        overlay.cancel_clicked.connect(dialog.close)
        overlay.show_export()
        self._export_overlay = overlay   # GC 방지

        job.start()
        dialog.show()

    def _sync_effects_enabled_menu(self) -> None:
        """활성 영상 탭의 사이드카 effects_enabled → 메뉴 체크 상태 (2026-05-20).

        탭 전환 / 사이드카 갱신 후 호출. 시그널 발화 방지를 위해 blockSignals.
        """
        tab = self.tab_area.current_video_tab() if hasattr(self.tab_area, "current_video_tab") else None
        if tab is None:
            return
        action = getattr(self.menu_bar, "toggle_effects_enabled_action", None)
        if action is None:
            return
        enabled = bool(tab._edit_controller.sidecar().effects_enabled)
        action.blockSignals(True)
        try:
            action.setChecked(enabled)
        finally:
            action.blockSignals(False)

    def _on_gpu_acceleration_setup(self) -> None:
        """편집 → 'GPU 가속 활성화…' — 상태에 따라 분기 (2026-05-20 사용자 요청 1-클릭 설치).

        - active: 이미 활성 — 안내 모달만.
        - installed_pending_restart: pip 패키지 깔려 있지만 재시작 필요 — 안내.
        - not_installed: 확인 다이얼로그 → 진행 다이얼로그 (별창, 비모달).
        - no_gpu: NVIDIA GPU 자체 없음 — 안내 모달.
        """
        from PySide6.QtWidgets import QMessageBox
        from ..agent.transcript import gpu_acceleration_status

        status = gpu_acceleration_status()
        if status == "active":
            QMessageBox.information(
                self, "GPU 가속 활성화됨",
                "이미 GPU 가속이 활성화되어 있습니다.\n"
                "자막 내보내기는 NVIDIA GPU 를 사용합니다.",
            )
            return
        if status == "no_gpu":
            QMessageBox.information(
                self, "NVIDIA GPU 미감지",
                "이 PC 에서 NVIDIA GPU 를 찾을 수 없습니다.\n"
                "자막 내보내기는 CPU 모드로 동작합니다.\n\n"
                "(다른 GPU 가속은 추후 지원 검토 중)",
            )
            return
        if status == "installed_pending_restart":
            QMessageBox.information(
                self, "재시작 필요",
                "GPU 가속 라이브러리는 이미 설치되어 있습니다.\n"
                "KStudio 를 재시작하면 활성화됩니다.",
            )
            return
        # not_installed — 확인 후 진행 다이얼로그 열기.
        ans = QMessageBox.question(
            self, "GPU 가속 설치",
            "NVIDIA cuBLAS / cuDNN 라이브러리를 자동 설치합니다.\n"
            "약 1.5GB 다운로드 — 인터넷 속도에 따라 수 분 ~ 십수 분 소요.\n\n"
            "계속하시겠어요?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        from .gpu_install_dialog import GpuInstallDialog
        dlg = GpuInstallDialog(self)
        dlg.finished_ok.connect(self._on_gpu_install_finished_ok)
        dlg.show()
        self._gpu_install_dialog = dlg   # GC 방지 — 비모달이라 강한 참조 필요.

    def _on_gpu_install_finished_ok(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "설치 완료",
            "GPU 가속 라이브러리 설치 완료.\n"
            "변경 사항은 KStudio 를 재시작해야 적용됩니다.",
        )

    def _on_toggle_effects_enabled(self, checked: bool) -> None:
        """편집 → '효과 적용' 체크 토글 — 활성 영상 탭의 사이드카에 반영 (2026-05-20).

        사용자가 체크 해제 → 사이드카.effects_enabled=False → preview/export 모두 효과 무시.
        체크 → 다시 ON. 체크 상태 동기화는 활성 탭 전환 시 _sync_effects_enabled_menu 에서.
        """
        tab = self.tab_area.current_video_tab() if hasattr(self.tab_area, "current_video_tab") else None
        if tab is None:
            return
        tab._edit_controller.set_effects_enabled(bool(checked))

    def _on_export_subtitle(self) -> None:
        """현재 활성 영상 탭의 음성을 Whisper 로 전사 → TXT/SRT 저장 (2026-05-20).

        흐름:
        1. 활성 영상 탭 확인
        2. SubtitleExportSettingsDialog — 형식 (TXT/SRT) + Whisper 모델
        3. 저장 경로 선택
        4. SubtitleExportJob 백그라운드 실행 — Whisper 전사 + 파일 쓰기
        5. 진행 표시 (indeterminate — Whisper 는 중간 progress 어려움)
        """
        from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog
        from .subtitle_export_dialog import SubtitleExportSettingsDialog
        from ..encode.subtitle_export import SubtitleExportJob

        tab = self.tab_area.current_video_tab() if hasattr(self.tab_area, "current_video_tab") else None
        if tab is None:
            # 2026-05-20: 사용자 보고 — 영상 안 열고 메뉴 누르면 silent return 으로
            # "창이 안 뜬다" 인지. 명시 안내로 가시화.
            QMessageBox.information(
                self, "자막 내보내기",
                "자막을 추출할 영상을 먼저 열거나 활성 탭으로 전환해주세요.\n"
                "(자막 내보내기는 영상 모드 전용)",
            )
            return
        src_path = getattr(tab, "_source_path", None)
        if not src_path:
            QMessageBox.warning(
                self, "자막 내보내기",
                "활성 탭의 영상 경로를 찾을 수 없습니다.",
            )
            return

        # 1) 다이얼로그 — 사용자 settings 의 모델 기본값 사용.
        initial_model = getattr(self.app_settings.agent, "whisper_model_size", "base")
        dlg = SubtitleExportSettingsDialog(initial_model=initial_model, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        settings = dlg.current_settings()
        ext = dlg.suggested_extension()

        # 2) 저장 경로 — 원본 옆 <basename>.txt|.srt.
        default = Path(src_path).with_name(Path(src_path).stem + ext)
        filter_label = "텍스트 (*.txt)" if ext == ".txt" else "SRT 자막 (*.srt)"
        dst, _ = QFileDialog.getSaveFileName(
            self, "자막 파일 저장", str(default), filter_label,
        )
        if not dst:
            return
        dst = Path(dst)

        # 3) 사용자 settings 의 마지막 사용 모델 업데이트 (다음 호출 기본값).
        try:
            self.app_settings.agent.whisper_model_size = settings.model_size
        except AttributeError:
            pass   # AgentSettings 에 필드 없으면 무시 (방어적).

        # 4) 진행 별창 (비모달) — 사용자가 메인 앱 병행 사용 가능 (2026-05-20 명시).
        from .subtitle_export_progress import (
            SubtitleExportProgressWindow, wire_job_to_window,
        )
        window = SubtitleExportProgressWindow(model_size=settings.model_size, parent=self)
        # 5) 백그라운드 job — 시그널 4개 (download/transcribe/segment/phase) 로 진행.
        sidecar = tab._edit_controller.sidecar()
        job = SubtitleExportJob(
            media_path=src_path, settings=settings, dst_path=dst, sidecar=sidecar,
        )
        wire_job_to_window(
            job, window,
            open_folder_cb=self._open_in_explorer,
            gpu_install_cb=self._on_gpu_acceleration_setup,
        )
        self._subtitle_job = job   # GC 방지
        self._subtitle_window = window
        window.show()   # 비모달 — exec() 가 아닌 show()
        job.start()

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

    def _maybe_prewarm_webengine(self, force: bool = False) -> None:
        """문서 미리보기(QtWebEngine) compositing 을 미리 확정해 첫 진입 깜빡임 제거.

        깜빡임의 정체(2026-05-29 winId 오라클로 확정): 첫 QWebEngineView 가 실현될 때
        최상위 창의 네이티브 핸들(HWND)이 *재생성*되어 창 전체가 "닫혔다 열림". 1×1 로
        *보이는* WebEngine 자식을 미리 띄워 HWND 를 startup/전환 시점에 확정해 두면, 이후
        실제 문서 탭의 WebEngine 은 추가 자식이라 HWND 재생성이 없다(오라클: 빈 pre-warm
        만으로도 winId 불변 확인). 주의: *숨긴* 위젯은 HWND 가 안 생겨 무효 → 반드시 show().

        force:
          False(=startup) — 비문서 사용자에게 상시 Chromium 비용을 안 지우려
            last_mode=="document" 일 때만 warm.
          True(=문서 모드 진입) — gate 무시하고 즉시 warm. 이미지/영상으로 켰다가 문서로
            *전환*한 세션은 startup gate 를 못 타 첫 문서에서 깜빡이던 회귀 fix(2026-05-29).
            라이브러리는 모드별 필터라 문서는 반드시 이 전환 뒤에 열린다 → 전환 시 warm 이면
            첫 문서 클릭 전에 HWND 가 확정된다.

        세션당 1회(idempotent) — 이미 warm 했으면 즉시 반환. 비WebEngine/테스트 환경
        (KSTUDIO_DISABLE_WEBENGINE)은 비용 없이 스킵.
        """
        if self._webengine_prewarm is not None:
            return
        if os.environ.get("KSTUDIO_DISABLE_WEBENGINE") == "1":
            return
        if not force and self.app_settings.preferences.last_mode != "document":
            return
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except Exception:  # QtWebEngine 사용 불가 환경 — 미리보기도 fallback 이므로 무시.
            return
        view = QWebEngineView(self)
        view.setFixedSize(1, 1)
        view.move(0, 0)
        view.show()
        view.lower()
        # 네이티브 윈도우 실현(HWND 확정)은 이벤트 루프의 다음 paint 가 처리한다 — winId()
        # 로 동기 강제하면 이 환경에선 블록/행이 관측됨(2026-05-29 오라클). 문서 모드 전환과
        # 라이브러리 문서 클릭은 별개 사용자 동작이라 그 사이 이벤트 루프가 돌아 자연히
        # 실현된다(오라클 current 시나리오로 검증: winId 강제 없이도 HWND 재생성 0).
        self._webengine_prewarm = view

    def _update_image_clipboard_shortcuts(self) -> None:
        """이미지 편집용 Ctrl+C/X/A/D 단축키를 현재 탭이 EditTab 일 때만 켠다.

        EditTab 이 아니면(문서·영상 모드) 비활성화 → disabled QShortcut 은 shortcut
        매칭에서 빠지므로 Ctrl+C/X 가 포커스된 텍스트 위젯(마크다운 에디터·미리보기)
        또는 영상 타임라인 keyPressEvent 로 정상 전달된다.
        """
        enabled = self._current_screenshot_tab() is not None
        for sc in getattr(self, "_image_clipboard_shortcuts", []):
            sc.setEnabled(enabled)

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
        """Edit → 편집 모드 토글 (전역).

        영상 모드에서 메뉴 Ctrl+E 또는 메뉴 토글 → 모든 영상 탭에 동시 적용.
        """
        new_on = not self.app_settings.preferences.edit_mode_on
        self._on_global_edit_mode_change(new_on)

    def _on_global_edit_mode_change(self, on: bool) -> None:
        """전역 편집 모드 변경 — 모든 영상 탭에 동시 적용 + AppSettings 영속.

        사용자 결정 (2026-05-11): 편집 모드는 파일별 X, 전역 토글. 세션 간 유지.
        """
        on = bool(on)
        # 영속.
        self.app_settings.preferences.edit_mode_on = on
        # 모든 영상 탭에 적용 — 시그널 재발화로 인한 루프는 set_edit_mode 가 same value
        # no-op 처리하므로 안전.
        for w, _, _ in self.tab_area._tabs:
            if isinstance(w, VideoTab):
                try:
                    w.set_edit_mode(on)
                except (RuntimeError, AttributeError):
                    pass

    def _on_global_speed_effects_change(self, on: bool) -> None:
        """배속 일괄 켜기/끄기 — settings 영속 + 모든 영상 탭 + 인스펙터 패널 동기화."""
        on = bool(on)
        self.app_settings.preferences.speed_effects_enabled = on
        self._persist_settings()
        self.inspector_panel.set_speed_effects_enabled(on)
        for w, _, _ in self.tab_area._tabs:
            if isinstance(w, VideoTab):
                try:
                    w.set_speed_effects_enabled(on)
                except (RuntimeError, AttributeError):
                    pass

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

    def _refresh_video_tabs_sidecar_dir(self) -> None:
        """환경설정에서 사이드카 폴더가 변경된 경우 모든 영상 탭의 EditController 에 반영.

        Phase 19.5 — 새 영상 탭은 _resolve_sidecar_dir 로 자동 결정되지만, 이미 열린
        영상 탭의 EditController.SidecarStore 는 init 시 고정. 사용자가 환경설정에서
        폴더 바꿔도 기존 탭은 이전 폴더에 계속 저장하는 회귀 → 모든 탭에 즉시 반영.
        """
        new_dir = self._resolve_sidecar_dir()
        for w, _, _ in self.tab_area._tabs:
            if isinstance(w, VideoTab):
                try:
                    w._edit_controller.set_sidecar_dir(new_dir)
                except (RuntimeError, AttributeError):
                    pass

    def _open_preferences(self) -> None:
        dialog = PreferencesDialog(self.app_settings)
        # 환경설정의 사이드카 폴더 변경 → 모든 영상 탭에 즉시 반영.
        scp = getattr(dialog, "screenshot_panel", None)
        if scp is not None:
            scp.settings_changed.connect(self._refresh_video_tabs_sidecar_dir)
            scp.settings_changed.connect(self._persist_settings)
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
        # 일반 패널 변경 시 즉시 디스크에 저장 — 다이얼로그를 X 로 닫아도 유실 안 됨.
        pp = getattr(dialog, "preferences_panel", None)
        if pp is not None:
            pp.settings_changed.connect(self._persist_settings)
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
        # 모드별 마지막 활성 탭 기록 — 모드 토글 시 복원에 사용.
        cur_mode = self.mode_controller.mode()
        if eid is not None and cur_mode is not None:
            self._last_entry_per_mode[cur_mode] = eid
        # 2026-05-20: 활성 영상 탭의 사이드카에 맞춰 '효과 적용' 체크 메뉴 동기화.
        self._sync_effects_enabled_menu()
        # 이미지 편집용 Ctrl+C/X/A/D 단축키는 EditTab 활성 시에만 — 문서/영상 탭에선
        # 텍스트 위젯·타임라인이 Ctrl+C 를 받도록 비활성화.
        self._update_image_clipboard_shortcuts()

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

    # Phase 23: dock 가시성 영속 핸들러 — 메뉴 체크 변화를 settings 에 즉시 반영.
    def _on_library_dock_visibility_persist(self, checked: bool) -> None:
        self.app_settings.preferences.library_dock_visible = bool(checked)
        self._persist_settings()

    def _on_layers_dock_visibility_persist(self, checked: bool) -> None:
        self.app_settings.preferences.layers_dock_visible = bool(checked)
        self._persist_settings()

    def _on_record_status_dock_visibility_persist(self, checked: bool) -> None:
        self.app_settings.preferences.record_status_dock_visible = bool(checked)
        self._persist_settings()

    def _on_agent_panel_visibility_persist(self, checked: bool) -> None:
        """2026-05-27 추가 — 에이전트 패널 토글 영속화."""
        self.app_settings.preferences.agent_panel_visible = bool(checked)
        self._persist_settings()

    def _on_image_gen_dock_visibility_persist(self, checked: bool) -> None:
        """2026-05-27 추가 — 이미지 생성 패널 토글 영속화."""
        self.app_settings.preferences.image_gen_dock_visible = bool(checked)
        self._persist_settings()

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

    def _restore_initial_dock_layout(self) -> None:
        """첫 show 이후 호출되는 시작 모드 dock 레이아웃 복원 (showEvent 가 1회 스케줄).

        첫 show *이전* 에 restoreState 하면 일부 저장 레이아웃(특히 문서 모드 저장본)에서
        Qt 가 paint 단계에 크래시한다 (2026-05-29 사용자: 문서 모드로 종료 후 재시작 시 즉시
        종료). show 이후 복원은 런타임 모드 전환과 동일 경로라 안전. 모드별 키를 쓰되
        이미지는 레거시 dock_state_b64 fallback 유지."""
        mode = self.mode_controller.mode()
        prefs = self.app_settings.preferences
        if mode is AppMode.IMAGE:
            if not self._apply_dock_state_b64(prefs.dock_state_image_b64):
                self._apply_dock_state_b64(prefs.dock_state_b64)   # 레거시 fallback
        else:
            self._restore_dock_state_for_mode(mode)
        self._last_mode = mode
        # restoreState 가 가시성도 복원하므로 메뉴 체크 기준으로 다시 강제.
        self._enforce_dock_visibility()

    def _save_dock_state_for_mode(self, mode: AppMode) -> None:
        try:
            import base64
            state = bytes(self.saveState())
            attr = ("dock_state_image_b64" if mode is AppMode.IMAGE
                    else "dock_state_document_b64" if mode is AppMode.DOCUMENT
                    else "dock_state_video_b64")
            setattr(self.app_settings.preferences, attr,
                    base64.b64encode(state).decode("ascii"))
        except Exception:
            pass

    def _restore_dock_state_for_mode(self, mode: AppMode) -> None:
        prefs = self.app_settings.preferences
        b64 = (prefs.dock_state_image_b64 if mode is AppMode.IMAGE
               else prefs.dock_state_document_b64 if mode is AppMode.DOCUMENT
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
        # 시간/썸네일 분리 — 시간이 먼저 채워지고 썸네일은 별도 풀로 천천히.
        self._probe_duration_async(p, entry.id)
        self._extract_thumbnail_async(p, entry.id)

    # ---------- Phase 23: 라이브러리 영속 (recent files 모델) ----------
    _LIBRARY_MAX_ENTRIES = 50

    def _library_thumb_cache_dir(self) -> Path:
        d = _settings_module.settings_path().parent / "library_thumbs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _thumb_cache_key(self, file_path: Path) -> str:
        import hashlib
        s = str(Path(file_path).expanduser()).replace("\\", "/").lower()
        return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]

    def _thumb_cache_path(self, file_path: Path) -> Path:
        return self._library_thumb_cache_dir() / f"{self._thumb_cache_key(file_path)}.png"

    def _load_thumb_from_cache(self, file_path: Path) -> "QImage | None":
        p = self._thumb_cache_path(file_path)
        if not p.exists():
            return None
        img = QImage(str(p))
        return img if not img.isNull() else None

    def _save_thumb_to_cache(self, file_path: Path, image: QImage) -> None:
        try:
            cache_path = self._thumb_cache_path(file_path)
            image.save(str(cache_path), "PNG")
        except (OSError, RuntimeError):
            pass

    def _delete_thumb_cache(self, file_path: Path) -> None:
        try:
            p = self._thumb_cache_path(file_path)
            if p.exists():
                p.unlink()
        except OSError:
            pass

    def _load_persisted_library(self) -> None:
        """settings.recent_library_entries 에서 라이브러리 복원. path 없는/사라진 항목은 스킵.

        썸네일: 캐시 hit 시 즉시 적용, miss 시 placeholder + 백그라운드 재추출.
        오래된 → 최신 순서로 add → LibraryPanel 이 최신을 맨 위에 끼워 넣음.
        """
        raw_entries = list(self.app_settings.preferences.recent_library_entries or [])
        # 점진적 추가용 큐 — 한 번에 다 넣으면 UI 멈춤 가능.
        survivors: list[dict] = []
        for d in raw_entries:
            try:
                path_str = d.get("path") or ""
                if not path_str:
                    continue
                p = Path(path_str)
                if not p.exists():
                    # 파일 사라짐 → 캐시도 정리 + 스킵.
                    self._delete_thumb_cache(p)
                    continue
                survivors.append(d)
            except (TypeError, OSError):
                continue

        # created_at 기준 정렬 (오래된 → 최신). 없으면 그대로.
        def _sort_key(d):
            return d.get("created_at") or ""
        survivors.sort(key=_sort_key)

        self._persist_restore_queue = survivors
        QTimer.singleShot(150, self._restore_one_library_entry)

    def _restore_one_library_entry(self) -> None:
        """복원 큐에서 1개씩 add — event loop yield 로 UI 멈춤 방지."""
        queue = getattr(self, "_persist_restore_queue", None)
        if not queue:
            return
        d = queue.pop(0)
        try:
            kind_str = d.get("kind") or "image"
            if kind_str == "video":
                kind = EntryKind.VIDEO
            elif kind_str == "document":
                kind = EntryKind.DOCUMENT
            else:
                kind = EntryKind.IMAGE
            p = Path(d["path"])
            display_name = d.get("display_name") or p.name
            duration_ms = int(d.get("duration_ms") or 0)
            origin = d.get("origin") or "opened"

            # 썸네일 — 문서는 썸네일 없음(📄 라벨로 구분), 나머지는 캐시 hit/placeholder.
            if kind is EntryKind.DOCUMENT:
                cached = None
                thumb = QImage()
            else:
                cached = self._load_thumb_from_cache(p)
                if cached is not None:
                    thumb = cached
                else:
                    thumb = QImage(64, 36, QImage.Format_ARGB32)
                    thumb.fill(0xFF222222)

            entry = self.library_model.add(
                kind, thumbnail=thumb,
                source_label="opened",
                display_name=display_name,
                path=p, duration_ms=duration_ms, origin=origin,
            )
            if cached is None:
                if kind is EntryKind.IMAGE:
                    if p.suffix.lower() != ".kstudio":
                        self._decode_image_thumb_async(p, entry.id)
                elif kind is EntryKind.VIDEO:
                    if duration_ms <= 0:
                        self._probe_duration_async(p, entry.id)
                    self._extract_thumbnail_async(p, entry.id)
                # DOCUMENT: 썸네일/길이 추출 없음.
        except (KeyError, OSError, ValueError):
            pass
        if queue:
            QTimer.singleShot(0, self._restore_one_library_entry)

    def _setup_library_persistence(self) -> None:
        """라이브러리 변경 → settings 에 즉시 저장 (디바운스 200ms).
        외부 삭제 감지용 폴더 watcher 는 더 이상 사용 안 함 (폴더 스캔 모델 폐기).
        """
        self._library_save_timer = QTimer(self)
        self._library_save_timer.setSingleShot(True)
        self._library_save_timer.setInterval(200)
        self._library_save_timer.timeout.connect(self._save_library_to_settings)
        # entry id → path 매핑 (제거 시 캐시 삭제용 — remove 시그널이 id 만 전달).
        self._library_entry_paths: dict = {}

        def _schedule(*_args):
            self._library_save_timer.start()

        self.library_model.entry_added.connect(self._on_library_entry_added_for_persist)
        self.library_model.entry_added.connect(_schedule)
        self.library_model.entry_renamed.connect(_schedule)
        self.library_model.entry_removed.connect(self._on_library_entry_removed_for_cache)
        self.library_model.entry_removed.connect(_schedule)

    def _on_library_entry_added_for_persist(self, entry) -> None:
        """entry_added 직후 path 매핑 갱신 — 나중 remove 시 캐시 정리에 사용."""
        if entry.path is not None:
            self._library_entry_paths[entry.id] = Path(entry.path)

    def _on_library_entry_removed_for_cache(self, entry_id: int) -> None:
        """entry 제거 직전에 저장해 둔 path 로 썸네일 캐시 정리."""
        path = self._library_entry_paths.pop(entry_id, None)
        if path is not None:
            self._delete_thumb_cache(path)

    def _save_library_to_settings(self) -> None:
        """현재 LibraryModel 내용을 settings.recent_library_entries 에 직렬화 + 저장.
        최신 50개만 유지 (entries() 가 최신순 reversed 반환하므로 head 50)."""
        try:
            entries = self.library_model.entries()    # 최신 → 오래된
            entries = entries[: self._LIBRARY_MAX_ENTRIES]
            serialized: list[dict] = []
            # 저장은 오래된 → 최신 순서로 (시작 시 복원 sort 와 일관).
            for e in reversed(entries):
                if e.path is None:
                    continue
                serialized.append({
                    "kind": e.kind.value,
                    "path": str(e.path),
                    "display_name": e.display_name,
                    "duration_ms": int(e.duration_ms or 0),
                    "origin": e.origin,
                    "created_at": e.created_at.isoformat() if e.created_at else "",
                })
            self.app_settings.preferences.recent_library_entries = serialized
            self._persist_settings()
        except (OSError, AttributeError) as exc:
            logging.getLogger(__name__).warning("library persist failed: %s", exc)

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
        self._probe_duration_async(out, entry.id)
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

    def _probe_duration_ms(self, path: Path) -> int:
        """ffprobe 로 영상 길이 (ms) 조회. 실패 시 0.

        ffmpeg 과 같은 폴더에 있는 ffprobe 를 우선 사용 — 번들 환경 + PATH 양쪽 모두
        지원. CREATE_NO_WINDOW 로 콘솔 깜박임 방지 (Windows).
        """
        import subprocess
        import sys
        try:
            if not path.exists():
                return 0
            ffprobe = self.ffmpeg_path.parent / (
                "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
            )
            candidate = str(ffprobe) if ffprobe.exists() else "ffprobe"
            no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            result = subprocess.run(
                [candidate, "-v", "error",
                 "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1",
                 str(path)],
                capture_output=True, timeout=10,
                creationflags=no_window,
            )
            if result.returncode != 0:
                return 0
            text = result.stdout.decode("utf-8", "replace").strip()
            if not text:
                return 0
            return int(round(float(text) * 1000))
        except (subprocess.SubprocessError, FileNotFoundError, OSError, ValueError):
            return 0

    def _decode_image_thumb_async(self, path: Path, entry_id: int) -> None:
        """이미지 파일을 백그라운드 스레드에서 디코딩 + 128×128 축소 → 라이브러리 갱신.

        QImage 는 reentrant (스레드별 인스턴스 OK) — 워커 스레드에서 만든 QImage 를
        QueuedConnection 으로 메인 스레드에 전달. 시작 시 이미지 12개 PNG 동기 디코딩이
        2초+ 메인 스레드 block 하던 문제 fix. ffmpeg 가 필요 없는 가벼운 작업이라
        duration probe 와 같은 풀 (max_workers=2) 공유.
        """
        from PySide6.QtCore import QMetaObject, Qt as Qt2, Q_ARG

        def _worker():
            try:
                img = QImage(str(path))
                if img.isNull():
                    return
                thumb = img.scaled(
                    128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
            except Exception:
                return
            QMetaObject.invokeMethod(
                self, "_apply_thumbnail",
                Qt2.QueuedConnection,
                Q_ARG(int, entry_id),
                Q_ARG(QImage, thumb),
            )

        if not hasattr(self, "_duration_probe_pool"):
            from concurrent.futures import ThreadPoolExecutor
            self._duration_probe_pool = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="DurationProbe"
            )
        self._duration_probe_pool.submit(_worker)

    def _probe_duration_async(self, path: Path, entry_id: int) -> None:
        """ffprobe 로 duration 만 비동기 조회 → LibraryModel 갱신.

        ffprobe 는 metadata 만 읽으므로 영상당 ~50ms 이내. 시작 시 라이브러리의
        모든 영상에 대해 빠르게 시간이 채워지도록 별도 풀 (max_workers=2) 사용 —
        썸네일(ffmpeg 첫 프레임 추출, 영상당 수백ms~수초) 과 분리해 시간 인덱싱이
        썸네일에 발목 잡히지 않게 한다.
        """
        from PySide6.QtCore import QMetaObject, Qt as Qt2, Q_ARG

        def _worker():
            dur = self._probe_duration_ms(path)
            if dur > 0:
                QMetaObject.invokeMethod(
                    self, "_apply_entry_duration",
                    Qt2.QueuedConnection,
                    Q_ARG(int, entry_id),
                    Q_ARG(int, dur),
                )

        if not hasattr(self, "_duration_probe_pool"):
            from concurrent.futures import ThreadPoolExecutor
            self._duration_probe_pool = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="DurationProbe"
            )
        self._duration_probe_pool.submit(_worker)

    def _extract_thumbnail_async(self, path: Path, entry_id: int) -> None:
        """ffmpeg 으로 첫 프레임 썸네일을 비동기 추출 → LibraryModel 갱신.

        ffmpeg 첫 프레임 추출은 영상당 수백ms~수초로 무거움. 시작 시 라이브러리에
        영상이 많아도 (50+) CPU·디스크 경합 최소화를 위해 max_workers=1 풀로 순차
        처리. duration 은 별도 `_probe_duration_async` 가 빠르게 채워주므로 썸네일이
        늦더라도 사용자가 시간/이름은 즉시 확인 가능.
        """
        from PySide6.QtCore import QMetaObject, Qt as Qt2, Q_ARG

        def _worker():
            img = self._extract_first_frame(path)
            if not img.isNull():
                QMetaObject.invokeMethod(
                    self, "_apply_thumbnail",
                    Qt2.QueuedConnection,
                    Q_ARG(int, entry_id),
                    Q_ARG(QImage, img),
                )

        if not hasattr(self, "_thumb_probe_pool"):
            from concurrent.futures import ThreadPoolExecutor
            self._thumb_probe_pool = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="ThumbnailExtract"
            )
        self._thumb_probe_pool.submit(_worker)

    @Slot(int, int)
    def _apply_entry_duration(self, entry_id: int, duration_ms: int) -> None:
        """백그라운드 ffprobe 결과를 라이브러리 entry 에 반영 (재사용 가능 한 진입점)."""
        self._on_video_duration_resolved(entry_id, duration_ms)

    @Slot(int, QImage)
    def _apply_thumbnail(self, entry_id: int, image: QImage) -> None:
        """백그라운드 썸네일 추출 결과를 라이브러리 엔트리에 반영."""
        entry = self.library_model.get(entry_id)
        if entry is None:
            return
        entry.thumbnail = image
        # 다음 실행 시 재사용 — library_thumbs/{hash}.png 에 저장.
        if entry.path is not None:
            self._save_thumb_to_cache(entry.path, image)
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
        # __init__ 이 487 라인(`_mcp_bridge = None`) 도달 전에 예외로 중단되면
        # closeEvent 가 부분 초기화 self 로 호출돼 AttributeError 가 났던 회귀.
        bridge = getattr(self, "_mcp_bridge", None)
        if bridge is not None:
            try:
                bridge.stop()
            except Exception:   # noqa: BLE001
                pass
            self._mcp_bridge = None
            self._mcp_dispatcher = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        overlay = getattr(self, "_export_overlay", None)
        if overlay is not None and overlay.isVisible():
            overlay.reposition()

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
        # 모든 영상 탭의 autosave 디바운스를 즉시 flush — 사용자 보고 데이터 손실 fix.
        for w, _, _ in self.tab_area._tabs:
            try:
                if hasattr(w, "edit_controller"):
                    w.edit_controller().flush_autosave()
            except (RuntimeError, AttributeError):
                pass
        # 메인 창 위치/크기 영속화 (app/main.py 의 종료 hook 이 settings.save 호출).
        # 최대화/최소화 상태에서는 geometry() 가 모니터 전체 크기를 반환하므로 그걸 그대로
        # 저장하면 다음 실행 시 최대화 해제해도 거대한 일반 창이 남는 회귀가 난다.
        # normalGeometry() 는 showNormal() 시 복원될 "일반 창 크기" 를 별도로 보관한다.
        is_max = self.isMaximized()
        g = self.normalGeometry() if (is_max or self.isMinimized()) else self.geometry()
        self.app_settings.screenshot.viewer_x = g.x()
        self.app_settings.screenshot.viewer_y = g.y()
        self.app_settings.screenshot.viewer_w = g.width()
        self.app_settings.screenshot.viewer_h = g.height()
        self.app_settings.screenshot.viewer_maximized = is_max
        # dock 레이아웃 영속화 — 현재 모드 기준.
        self._save_dock_state_for_mode(self.mode_controller.mode())
        self.hotkeys.shutdown()
        self._stop_mcp_bridge()
        # 대화 기록 즉시 flush (디바운스 우회) — 종료 race 방지.
        try:
            self.agent_chat_panel.flush_history_now()
        except (RuntimeError, AttributeError):
            pass
        # Claude 에이전트 worker thread 정리 — asyncio loop 종료 + QThread join.
        try:
            self.agent_runtime.stop()
        except (RuntimeError, AttributeError):
            pass
        # 이미지 생성 worker / VRAM 정리 (lazy 생성됐을 때만).
        if self.image_gen_dialog is not None:
            try:
                self.image_gen_dialog.shutdown()
            except (RuntimeError, AttributeError):
                pass
        self._hide_border()
        e.accept()
