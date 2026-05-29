"""MarkdownTab — 코드 에디터 + 실시간 미리보기 + 3뷰 전환 (EditTab 계약 미러)."""
from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QHBoxLayout, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

from .markdown.editor import MarkdownEditor
from .markdown.highlighter import MarkdownHighlighter
from .markdown.preview import MarkdownPreview

_log = logging.getLogger(__name__)


class ViewMode(Enum):
    EDITOR = "editor"
    PREVIEW = "preview"
    SPLIT = "split"


def _read_text_with_fallback(path: Path) -> str:
    """UTF-8 우선 → utf-8-sig(BOM) → cp949 폴백. 모두 실패하면 replace 로 강제 디코드."""
    for enc in ("utf-8", "utf-8-sig", "cp949"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


class MarkdownTab(QWidget):
    save_state_changed = Signal()

    def __init__(self, *, source_label: str = "new") -> None:
        super().__init__()
        self._source_label = source_label
        self._saved_path: Path | None = None

        self._dirty = False
        self.editor = MarkdownEditor()
        self._highlighter = MarkdownHighlighter(self.editor.document())
        self.preview = MarkdownPreview()

        # 뷰모드 토글 버튼
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        self._btn_group = QButtonGroup(self)
        self._buttons: dict[ViewMode, QPushButton] = {}
        for mode, label in ((ViewMode.EDITOR, "✎ 편집"),
                            (ViewMode.PREVIEW, "👁 미리보기"),
                            (ViewMode.SPLIT, "⊟ 나란히")):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, m=mode: self.set_view_mode(m))
            self._btn_group.addButton(btn)
            self._buttons[mode] = btn
            bar.addWidget(btn)
        bar.addStretch(1)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self.editor)
        self._splitter.addWidget(self.preview)
        self._splitter.setSizes([500, 500])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self._splitter, stretch=1)

        # 편집 → 미리보기 갱신(디바운스) + dirty 추적(즉시).
        # QPlainTextEdit.setPlainText 는 modified 플래그를 올리지 않으므로(프로그램적 치환),
        # document().isModified() 대신 textChanged 기반 명시 _dirty 로 추적한다.
        self.editor.content_changed.connect(self._refresh_preview)
        self.editor.textChanged.connect(self._on_text_changed)

        self.set_view_mode(ViewMode.SPLIT)
        self._refresh_preview(self.editor.toPlainText())

    # --- 팩토리 ---
    @classmethod
    def from_blank(cls) -> "MarkdownTab":
        # 미저장 blank → saved_path None 이라 needs_save() 가 항상 True.
        return cls(source_label="new")

    @classmethod
    def from_file(cls, path: Path) -> "MarkdownTab":
        path = Path(path)
        text = _read_text_with_fallback(path)
        tab = cls(source_label="opened")
        tab.editor.setPlainText(text)   # textChanged → _dirty True 가 되므로
        tab._saved_path = path
        tab._dirty = False              # 막 로드한 파일은 깨끗한 상태
        tab.save_state_changed.emit()
        tab._refresh_preview(text)
        return tab

    # --- EditTab 계약 ---
    def source_label(self) -> str:
        return self._source_label

    def saved_path(self) -> Path | None:
        return self._saved_path

    def needs_save(self) -> bool:
        return (self._saved_path is None) or self._dirty

    def mark_saved(self, path: Path) -> None:
        self._saved_path = path
        self._dirty = False
        self.save_state_changed.emit()

    def _on_text_changed(self) -> None:
        if not self._dirty:
            self._dirty = True
            self.save_state_changed.emit()

    # --- 저장 ---
    def save(self) -> bool:
        if self._saved_path is None:
            return self.save_as()
        try:
            self._saved_path.write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as e:
            _log.error("Markdown 저장 실패: %s", e)
            return False
        self.mark_saved(self._saved_path)
        return True

    def save_as(self, path: Path | None = None) -> bool:
        if path is None:
            fn, _ = QFileDialog.getSaveFileName(
                self, "Markdown 저장", "", "Markdown (*.md *.markdown)"
            )
            if not fn:
                return False
            path = Path(fn)
        self._saved_path = Path(path)
        return self.save()

    # --- 뷰모드 ---
    def set_view_mode(self, mode: ViewMode) -> None:
        self._buttons[mode].setChecked(True)
        self.editor.setVisible(mode in (ViewMode.EDITOR, ViewMode.SPLIT))
        self.preview.setVisible(mode in (ViewMode.PREVIEW, ViewMode.SPLIT))

    def _refresh_preview(self, text: str) -> None:
        doc_dir = self._saved_path.parent if self._saved_path else None
        self.preview.set_content(text, doc_dir)

    def cleanup(self) -> None:
        """탭 닫힘 시 WebEngine 리소스 정리 (TabArea 가 호출)."""
        try:
            self.preview.deleteLater()
        except RuntimeError:
            pass
