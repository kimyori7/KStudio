"""KStudio 메뉴 바 — 파일/편집/이미지/보기/녹화/도움말."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenuBar


class KStudioMenuBar(QMenuBar):
    # 파일
    new_requested = Signal()
    open_requested = Signal()
    save_requested = Signal()
    save_as_requested = Signal()
    export_requested = Signal(str)        # "png" | "jpg" | "webp"
    open_save_folder_requested = Signal()
    quit_requested = Signal()
    # 편집
    undo_requested = Signal()
    redo_requested = Signal()
    preferences_requested = Signal()
    # 이미지
    background_remove_requested = Signal()
    # 보기
    original_zoom_requested = Signal()
    record_status_visibility_toggled = Signal(bool)
    # 창
    tool_palette_visibility_toggled = Signal(bool)
    layers_visibility_toggled = Signal(bool)
    library_visibility_toggled = Signal(bool)
    # 녹화
    record_start_requested = Signal()
    record_stop_requested = Signal()
    record_pause_requested = Signal()
    # 도움말
    about_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._build()

    def _build(self) -> None:
        m_file = self.addMenu("파일")
        self.new_action = QAction("새로 만들기…", self)
        self.new_action.setShortcut(QKeySequence("Ctrl+N"))
        self.new_action.triggered.connect(self.new_requested.emit)
        m_file.addAction(self.new_action)

        self.open_action = QAction("열기…", self)
        self.open_action.setShortcut(QKeySequence("Ctrl+O"))
        self.open_action.triggered.connect(self.open_requested.emit)
        m_file.addAction(self.open_action)

        m_file.addSeparator()

        self.save_action = QAction("저장", self)
        self.save_action.setShortcut(QKeySequence("Ctrl+S"))
        self.save_action.triggered.connect(self.save_requested.emit)
        m_file.addAction(self.save_action)

        self.save_as_action = QAction("다른 이름으로 저장…", self)
        self.save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_as_action.triggered.connect(self.save_as_requested.emit)
        m_file.addAction(self.save_as_action)

        # 내보내기 서브메뉴
        self.export_menu = m_file.addMenu("내보내기")
        self.export_menu_action = self.export_menu.menuAction()
        m_export = self.export_menu
        self.export_png_action = QAction("PNG", self)
        self.export_png_action.setShortcut(QKeySequence("Ctrl+E"))
        self.export_png_action.triggered.connect(lambda: self.export_requested.emit("png"))
        m_export.addAction(self.export_png_action)

        self.export_jpg_action = QAction("JPG", self)
        self.export_jpg_action.triggered.connect(lambda: self.export_requested.emit("jpg"))
        m_export.addAction(self.export_jpg_action)

        self.export_webp_action = QAction("WebP", self)
        self.export_webp_action.triggered.connect(lambda: self.export_requested.emit("webp"))
        m_export.addAction(self.export_webp_action)

        m_file.addSeparator()
        self.open_folder_action = QAction("저장 폴더 열기", self)
        self.open_folder_action.triggered.connect(self.open_save_folder_requested.emit)
        m_file.addAction(self.open_folder_action)

        m_file.addSeparator()
        self.quit_action = QAction("종료", self)
        self.quit_action.triggered.connect(self.quit_requested.emit)
        m_file.addAction(self.quit_action)

        m_edit = self.addMenu("편집")
        self.undo_action = QAction("실행취소", self)
        self.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self.undo_action.triggered.connect(self.undo_requested.emit)
        m_edit.addAction(self.undo_action)

        self.redo_action = QAction("다시실행", self)
        self.redo_action.setShortcut(QKeySequence("Ctrl+Y"))
        self.redo_action.triggered.connect(self.redo_requested.emit)
        m_edit.addAction(self.redo_action)

        m_edit.addSeparator()
        self.preferences_action = QAction("환경설정…", self)
        self.preferences_action.setShortcut(QKeySequence("Ctrl+,"))
        self.preferences_action.triggered.connect(self.preferences_requested.emit)
        m_edit.addAction(self.preferences_action)

        m_image = self.addMenu("이미지")
        self.background_remove_action = QAction("배경 제거 (누끼)", self)
        self.background_remove_action.setShortcut(QKeySequence("Ctrl+Shift+B"))
        self.background_remove_action.triggered.connect(self.background_remove_requested.emit)
        m_image.addAction(self.background_remove_action)

        m_view = self.addMenu("보기")
        self.original_action = QAction("원본 (100%)", self)
        self.original_action.setShortcut(QKeySequence("Ctrl+0"))
        self.original_action.triggered.connect(self.original_zoom_requested.emit)
        m_view.addAction(self.original_action)

        # 창 — 패널 가시성 토글 모음
        m_window = self.addMenu("창")
        self.tool_palette_visible_action = QAction("도구 팔레트", self)
        self.tool_palette_visible_action.setCheckable(True)
        self.tool_palette_visible_action.setChecked(True)
        self.tool_palette_visible_action.toggled.connect(self.tool_palette_visibility_toggled.emit)
        m_window.addAction(self.tool_palette_visible_action)

        self.library_visible_action = QAction("라이브러리", self)
        self.library_visible_action.setCheckable(True)
        self.library_visible_action.setChecked(True)
        self.library_visible_action.toggled.connect(self.library_visibility_toggled.emit)
        m_window.addAction(self.library_visible_action)

        m_window.addSeparator()
        # 모드별 전용 dock — 비-적용 모드에서는 자동으로 비활성화
        self.layers_visible_action = QAction("레이어 (이미지 모드 전용)", self)
        self.layers_visible_action.setCheckable(True)
        self.layers_visible_action.setChecked(True)
        self.layers_visible_action.toggled.connect(self.layers_visibility_toggled.emit)
        m_window.addAction(self.layers_visible_action)

        self.status_visible_action = QAction("녹화 상태 (영상 모드 전용)", self)
        self.status_visible_action.setCheckable(True)
        self.status_visible_action.setChecked(True)
        self.status_visible_action.toggled.connect(self.record_status_visibility_toggled.emit)
        m_window.addAction(self.status_visible_action)

        m_record = self.addMenu("녹화")
        self.record_start_action = QAction("녹화 시작", self)
        self.record_start_action.triggered.connect(self.record_start_requested.emit)
        m_record.addAction(self.record_start_action)

        self.record_stop_action = QAction("정지", self)
        self.record_stop_action.triggered.connect(self.record_stop_requested.emit)
        m_record.addAction(self.record_stop_action)

        self.record_pause_action = QAction("일시정지", self)
        self.record_pause_action.triggered.connect(self.record_pause_requested.emit)
        m_record.addAction(self.record_pause_action)

        m_help = self.addMenu("도움말")
        self.about_action = QAction("정보", self)
        self.about_action.triggered.connect(self.about_requested.emit)
        m_help.addAction(self.about_action)


def build_menu_bar(parent) -> dict[str, list[QAction]]:
    """KStudioMenuBar 인스턴스를 만들어 parent 에 부착한 뒤,
    메뉴 그룹별 QAction 목록을 dict 로 반환한다.

    테스트나 외부 와이어링에서 메뉴 항목을 이름으로 찾기 쉽도록 만든 헬퍼.
    실제 메뉴 동작은 `KStudioMenuBar` 의 시그널 기반 구조를 그대로 사용한다.
    """
    mb = KStudioMenuBar()
    parent.setMenuBar(mb)
    parent.menu_bar = mb  # type: ignore[attr-defined]
    return {
        "file": [
            mb.new_action,
            mb.open_action,
            mb.save_action,
            mb.save_as_action,
            mb.export_menu_action,
            mb.export_png_action,
            mb.export_jpg_action,
            mb.export_webp_action,
            mb.open_folder_action,
            mb.quit_action,
        ],
        "edit": [
            mb.undo_action,
            mb.redo_action,
            mb.preferences_action,
        ],
        "image": [
            mb.background_remove_action,
        ],
        "view": [
            mb.original_action,
        ],
        "window": [
            mb.tool_palette_visible_action,
            mb.library_visible_action,
            mb.layers_visible_action,
            mb.status_visible_action,
        ],
        "record": [
            mb.record_start_action,
            mb.record_stop_action,
            mb.record_pause_action,
        ],
        "help": [
            mb.about_action,
        ],
    }
