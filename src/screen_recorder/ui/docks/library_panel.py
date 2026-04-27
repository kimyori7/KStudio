"""라이브러리 패널 — 세션 결과물 썸네일 목록 (모드별 필터링)."""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QLabel

from ..library_model import LibraryEntry, LibraryModel, EntryKind
from ..mode_controller import AppMode, ModeController


def _format_duration(ms: int) -> str:
    s = max(0, ms // 1000)
    return f" ({s}s)" if s < 60 else f" ({s // 60}m{s % 60:02d}s)"


class LibraryPanel(QWidget):
    entry_open_requested = Signal(int)   # entry id

    def __init__(self, model: LibraryModel,
                 mode_controller: Optional[ModeController] = None) -> None:
        super().__init__()
        self._model = model
        self._mode = mode_controller
        self._items_by_id: dict[int, QListWidgetItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel("📋 라이브러리")
        title.setStyleSheet("color: #A0A4AB; font-weight: bold; padding: 2px 4px;")
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(48, 32))
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget, stretch=1)

        for e in self._model.entries():
            self._insert(e, at_top=False)

        model.entry_added.connect(lambda e: self._insert(e, at_top=True))
        model.entry_removed.connect(self._remove_by_id)

        if self._mode is not None:
            self._mode.mode_changed.connect(self._refresh_visibility)
            self._refresh_visibility(self._mode.mode())

    def _insert(self, entry: LibraryEntry, *, at_top: bool) -> None:
        prefix = "📸" if entry.kind is EntryKind.SCREENSHOT else "🎞"
        ts = entry.created_at.strftime("%H:%M")
        suffix = _format_duration(entry.duration_ms) if entry.kind is EntryKind.VIDEO else ""
        text = f"{prefix} {entry.source_label} {ts}{suffix}"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, entry.id)
        item.setData(Qt.UserRole + 1, entry.kind)
        if not entry.thumbnail.isNull():
            item.setIcon(QIcon(QPixmap.fromImage(entry.thumbnail).scaled(
                48, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )))
        if at_top:
            self.list_widget.insertItem(0, item)
        else:
            self.list_widget.addItem(item)
        self._items_by_id[entry.id] = item
        # 모드별 필터링 즉시 반영
        if self._mode is not None:
            wanted = self._kind_for_mode(self._mode.mode())
            item.setHidden(entry.kind is not wanted)

    def _remove_by_id(self, entry_id: int) -> None:
        item = self._items_by_id.pop(entry_id, None)
        if item is None:
            return
        row = self.list_widget.row(item)
        if row >= 0:
            self.list_widget.takeItem(row)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        eid = item.data(Qt.UserRole)
        if eid is not None:
            self.entry_open_requested.emit(int(eid))

    def _refresh_visibility(self, mode: AppMode) -> None:
        wanted = self._kind_for_mode(mode)
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            kind = it.data(Qt.UserRole + 1)
            it.setHidden(kind is not wanted)

    @staticmethod
    def _kind_for_mode(mode: AppMode) -> EntryKind:
        return EntryKind.VIDEO if mode is AppMode.VIDEO else EntryKind.SCREENSHOT
