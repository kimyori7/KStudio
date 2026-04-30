"""라이브러리 패널 — 세션 결과물 썸네일 목록 (모드별 필터링 + 컨텍스트 메뉴)."""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize, QPoint, QEvent
from PySide6.QtGui import QPixmap, QIcon, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QLabel, QMenu,
    QProxyStyle, QStyle,
)


class _FastTooltipStyle(QProxyStyle):
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_ToolTip_WakeUpDelay:
            return 500
        return super().styleHint(hint, option, widget, returnData)

from ..library_model import LibraryEntry, LibraryModel, EntryKind
from ..mode_controller import AppMode, ModeController


def _format_duration(ms: int) -> str:
    s = max(0, ms // 1000)
    return f" ({s}s)" if s < 60 else f" ({s // 60}m{s % 60:02d}s)"


class LibraryPanel(QWidget):
    entry_open_requested = Signal(int)       # entry id
    entry_rename_requested = Signal(int)     # entry id (UI 상에서 인라인 편집 시작 요청)
    entry_delete_requested = Signal(int)     # entry id
    entry_open_folder_requested = Signal(int)  # entry id
    entry_undelete_requested = Signal()       # Ctrl+Z — 마지막 삭제 항목 복원

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
        self.list_widget.itemChanged.connect(self._on_item_changed)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.list_widget.installEventFilter(self)
        self.list_widget.setStyle(_FastTooltipStyle(self.list_widget.style()))
        layout.addWidget(self.list_widget, stretch=1)

        for e in self._model.entries():
            self._insert(e, at_top=False)

        model.entry_added.connect(lambda e: self._insert(e, at_top=True))
        model.entry_removed.connect(self._remove_by_id)
        model.entry_renamed.connect(self._on_entry_renamed)

        if self._mode is not None:
            self._mode.mode_changed.connect(self._refresh_visibility)
            self._refresh_visibility(self._mode.mode())

    # ---------- 모델 → UI ----------
    def _insert(self, entry: LibraryEntry, *, at_top: bool) -> None:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, entry.id)
        item.setData(Qt.UserRole + 1, entry.kind)
        item.setText(self._render_text(entry))
        item.setToolTip(entry.display_name or entry.source_label)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        if not entry.thumbnail.isNull():
            item.setIcon(QIcon(QPixmap.fromImage(entry.thumbnail).scaled(
                48, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )))
        if at_top:
            self.list_widget.insertItem(0, item)
        else:
            self.list_widget.addItem(item)
        self._items_by_id[entry.id] = item
        if self._mode is not None:
            wanted = self._kind_for_mode(self._mode.mode())
            item.setHidden(entry.kind is not wanted)

    @staticmethod
    def _render_text(entry: LibraryEntry) -> str:
        prefix = "📸" if entry.kind is EntryKind.SCREENSHOT else "🎞"
        if entry.display_name:
            base = entry.display_name
        else:
            ts = entry.created_at.strftime("%H:%M")
            base = f"{entry.source_label} {ts}"
        suffix = _format_duration(entry.duration_ms) if entry.kind is EntryKind.VIDEO else ""
        return f"{prefix} {base}{suffix}"

    def focus_entry(self, entry_id: int) -> None:
        """외부에서 호출 — 해당 entry 의 list item 을 선택 상태로 (탭과 동기화)."""
        item = self._items_by_id.get(entry_id)
        if item is None:
            return
        # itemClicked 가 다시 발화하지 않도록 차단 (currentItemChanged 와 itemClicked 분리)
        self.list_widget.blockSignals(True)
        try:
            self.list_widget.setCurrentItem(item)
            self.list_widget.scrollToItem(item)
        finally:
            self.list_widget.blockSignals(False)

    def _remove_by_id(self, entry_id: int) -> None:
        item = self._items_by_id.pop(entry_id, None)
        if item is None:
            return
        row = self.list_widget.row(item)
        if row >= 0:
            self.list_widget.takeItem(row)
        # 영상 탭이 닫히는 동안 (수백 ms) Qt 가 list 위젯 repaint 를 늦추는 경우가 있어
        # 즉각 반영되도록 viewport 강제 갱신. 사용자가 Del 후 같은 모드 안에서도 제거를
        # 바로 눈으로 확인할 수 있게 하기 위함.
        self.list_widget.viewport().update()

    def _on_entry_renamed(self, entry_id: int, _new_name: str) -> None:
        item = self._items_by_id.get(entry_id)
        if item is None:
            return
        entry = self._model.get(entry_id)
        if entry is None:
            return
        # itemChanged 가 다시 발화하지 않도록 차단
        self.list_widget.blockSignals(True)
        try:
            item.setText(self._render_text(entry))
            item.setToolTip(entry.display_name or entry.source_label)
            if not entry.thumbnail.isNull():
                item.setIcon(QIcon(QPixmap.fromImage(entry.thumbnail).scaled(
                    48, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )))
        finally:
            self.list_widget.blockSignals(False)

    # ---------- UI → 외부 ----------
    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        eid = item.data(Qt.UserRole)
        if eid is not None:
            self.entry_open_requested.emit(int(eid))

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """인라인 편집으로 텍스트가 바뀜 — 사용자가 입력한 텍스트에서 prefix/접미사를 떼고
        새 display_name 만 추출한 뒤 모델/디스크에 반영하도록 외부에 위임."""
        eid = item.data(Qt.UserRole)
        if eid is None:
            return
        entry = self._model.get(int(eid))
        if entry is None:
            return
        # 사용자가 직접 텍스트 박스 편집을 끝낸 경우만 처리 — _render_text 와 같으면 noop
        new_text = item.text()
        # prefix 제거: "📸 " 또는 "🎞 " 로 시작
        for pfx in ("📸 ", "🎞 "):
            if new_text.startswith(pfx):
                new_text = new_text[len(pfx):]
                break
        # duration suffix 제거: " (32s)" 등
        if entry.kind is EntryKind.VIDEO:
            sfx = _format_duration(entry.duration_ms)
            if sfx and new_text.endswith(sfx):
                new_text = new_text[:-len(sfx)]
        new_display = new_text.strip()
        if new_display == entry.display_name:
            # 변경 없음 — 텍스트 정규화만 다시 적용
            self._on_entry_renamed(entry.id, entry.display_name)
            return
        if not new_display:
            # 빈 이름 거부 — 원복
            self._on_entry_renamed(entry.id, entry.display_name)
            return
        # 외부(MainWindow)가 받아 디스크 rename + model.rename 처리
        self.entry_rename_requested.emit(int(eid))
        # 일단 모델만 업데이트 — MainWindow 가 시그널 받은 뒤 디스크 처리
        # NOTE: rename_requested 만 emit 하면 MainWindow 에서 prompt 하지 않고 인라인 텍스트 사용해야 함.
        # 단순화: 인라인 편집 결과를 직접 모델에 반영하고, 디스크 rename 만 MainWindow 에 위임.
        self._model.rename(entry.id, new_display)

    def eventFilter(self, obj, event: QEvent) -> bool:
        if obj is self.list_widget and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Delete:
                item = self.list_widget.currentItem()
                if item is not None:
                    eid = item.data(Qt.UserRole)
                    if eid is not None:
                        self.entry_delete_requested.emit(int(eid))
                return True
            # Ctrl+Z — 마지막 Del 을 휴지통에서 되돌리는 요청. 실제 복원 로직은 MainWindow.
            if event.key() == Qt.Key_Z and (event.modifiers() & Qt.ControlModifier):
                self.entry_undelete_requested.emit()
                return True
        return super().eventFilter(obj, event)

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        eid = item.data(Qt.UserRole)
        if eid is None:
            return
        eid = int(eid)
        menu = QMenu(self)
        rename_action = QAction("이름 바꾸기 (F2)", self)
        rename_action.triggered.connect(lambda: self.list_widget.editItem(item))
        menu.addAction(rename_action)

        open_folder_action = QAction("저장 폴더 열기", self)
        open_folder_action.triggered.connect(
            lambda: self.entry_open_folder_requested.emit(eid)
        )
        menu.addAction(open_folder_action)

        menu.addSeparator()
        delete_action = QAction("삭제 (휴지통)", self)
        delete_action.triggered.connect(
            lambda: self.entry_delete_requested.emit(eid)
        )
        menu.addAction(delete_action)

        menu.exec(self.list_widget.viewport().mapToGlobal(pos))

    def _refresh_visibility(self, mode: AppMode) -> None:
        wanted = self._kind_for_mode(mode)
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            kind = it.data(Qt.UserRole + 1)
            it.setHidden(kind is not wanted)

    @staticmethod
    def _kind_for_mode(mode: AppMode) -> EntryKind:
        return EntryKind.VIDEO if mode is AppMode.VIDEO else EntryKind.SCREENSHOT
