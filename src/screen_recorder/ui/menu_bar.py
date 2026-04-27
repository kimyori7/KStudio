"""KStudio 메뉴 바 — 파일/편집/보기/녹화/도움말."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenuBar


class KStudioMenuBar(QMenuBar):
    # 파일
    save_requested = Signal()
    save_as_requested = Signal()
    open_save_folder_requested = Signal()
    quit_requested = Signal()
    # 편집
    undo_requested = Signal()
    redo_requested = Signal()
    preferences_requested = Signal()
    # 보기
    original_zoom_requested = Signal()
    library_visibility_toggled = Signal(bool)
    record_status_visibility_toggled = Signal(bool)
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
        self.save_action = QAction("저장", self)
        self.save_action.setShortcut(QKeySequence("Ctrl+S"))
        self.save_action.triggered.connect(self.save_requested.emit)
        m_file.addAction(self.save_action)

        self.save_as_action = QAction("다른 이름으로 저장", self)
        self.save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_as_action.triggered.connect(self.save_as_requested.emit)
        m_file.addAction(self.save_as_action)

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

        m_view = self.addMenu("보기")
        self.original_action = QAction("원본 (100%)", self)
        self.original_action.setShortcut(QKeySequence("Ctrl+0"))
        self.original_action.triggered.connect(self.original_zoom_requested.emit)
        m_view.addAction(self.original_action)

        m_view.addSeparator()
        self.library_visible_action = QAction("라이브러리 표시", self)
        self.library_visible_action.setCheckable(True)
        self.library_visible_action.setChecked(True)
        self.library_visible_action.toggled.connect(self.library_visibility_toggled.emit)
        m_view.addAction(self.library_visible_action)

        self.status_visible_action = QAction("녹화 상태 표시", self)
        self.status_visible_action.setCheckable(True)
        self.status_visible_action.setChecked(True)
        self.status_visible_action.toggled.connect(self.record_status_visibility_toggled.emit)
        m_view.addAction(self.status_visible_action)

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
