"""라이브러리 패널 — 세션 결과물 썸네일 목록 (모드별 필터링 + 컨텍스트 메뉴)."""
from __future__ import annotations
from typing import Optional

from pathlib import Path as _Path

from PySide6.QtCore import Qt, Signal, QSize, QPoint, QEvent, QRect
from PySide6.QtGui import (
    QPixmap, QIcon, QAction, QPainter, QFont, QFontMetrics, QColor,
    QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QLabel, QMenu,
    QProxyStyle, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QApplication,
)


class _FastTooltipStyle(QProxyStyle):
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_ToolTip_WakeUpDelay:
            return 500
        return super().styleHint(hint, option, widget, returnData)


_ROLE_FOLDER = Qt.UserRole + 2   # 윗줄에 표시할 폴더 경로

from ..library_model import LibraryEntry, LibraryModel, EntryKind
from ..mode_controller import AppMode, ModeController


class _TwoLineDelegate(QStyledItemDelegate):
    """라이브러리 항목 2줄 표시 — 위: 폴더 (작게·흐리게), 아래: 파일명.

    인라인 편집은 Qt.DisplayRole (= 파일명) 만 대상으로 두므로 기존 rename 로직
    영향 없음.
    """
    _PADDING = 4
    _ICON_TEXT_GAP = 6
    _LINE_GAP = 2

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        s = super().sizeHint(option, index)
        folder_font = QFont(option.font)
        folder_font.setPointSizeF(max(7.0, folder_font.pointSizeF() - 1.0))
        folder_h = QFontMetrics(folder_font).height()
        name_h = QFontMetrics(option.font).height()
        text_h = folder_h + self._LINE_GAP + name_h + self._PADDING * 2
        icon_h = option.decorationSize.height() + self._PADDING * 2
        return QSize(s.width(), max(text_h, icon_h))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        # 1. 배경 / selection — style.drawControl(CE_ItemViewItem) 은 PySide6 +
        #    proxy style (_FastTooltipStyle) 와 access violation 충돌 → 직접 그림.
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, option.palette.alternateBase())

        rect = option.rect.adjusted(self._PADDING, self._PADDING,
                                     -self._PADDING, -self._PADDING)

        # 2. 아이콘.
        icon = index.data(Qt.DecorationRole)
        icon_w = option.decorationSize.width()
        icon_h = option.decorationSize.height()
        icon_rect = QRect(rect.left(),
                          rect.top() + (rect.height() - icon_h) // 2,
                          icon_w, icon_h)
        if icon is not None and not icon.isNull():
            icon.paint(painter, icon_rect, Qt.AlignCenter)

        # 3. 텍스트 영역.
        text_left = icon_rect.right() + self._ICON_TEXT_GAP
        text_rect = QRect(text_left, rect.top(),
                          max(0, rect.right() - text_left), rect.height())

        folder = index.data(_ROLE_FOLDER) or ""
        filename = index.data(Qt.DisplayRole) or ""

        if option.state & QStyle.State_Selected:
            base_color = option.palette.highlightedText().color()
        else:
            base_color = option.palette.text().color()

        folder_font = QFont(option.font)
        folder_font.setPointSizeF(max(7.0, folder_font.pointSizeF() - 1.0))
        folder_fm = QFontMetrics(folder_font)
        name_fm = QFontMetrics(option.font)
        folder_h = folder_fm.height()
        name_h = name_fm.height()

        # 폴더가 있을 때만 2줄로 — 없으면 파일명만 가운데 정렬.
        if folder:
            total_h = folder_h + self._LINE_GAP + name_h
            top = text_rect.top() + (text_rect.height() - total_h) // 2

            painter.setFont(folder_font)
            if option.state & QStyle.State_Selected:
                folder_color = base_color
            else:
                folder_color = QColor(base_color)
                folder_color.setAlphaF(0.55)
            painter.setPen(folder_color)
            folder_elided = folder_fm.elidedText(
                folder, Qt.ElideMiddle, text_rect.width()
            )
            painter.drawText(text_rect.left(), top + folder_fm.ascent(), folder_elided)

            painter.setFont(option.font)
            painter.setPen(base_color)
            name_elided = name_fm.elidedText(
                filename, Qt.ElideRight, text_rect.width()
            )
            painter.drawText(
                text_rect.left(),
                top + folder_h + self._LINE_GAP + name_fm.ascent(),
                name_elided,
            )
        else:
            top = text_rect.top() + (text_rect.height() - name_h) // 2
            painter.setFont(option.font)
            painter.setPen(base_color)
            name_elided = name_fm.elidedText(
                filename, Qt.ElideRight, text_rect.width()
            )
            painter.drawText(text_rect.left(), top + name_fm.ascent(), name_elided)

        painter.restore()


def _format_duration(ms: int) -> str:
    s = max(0, ms // 1000)
    return f" ({s}s)" if s < 60 else f" ({s // 60}m{s % 60:02d}s)"


class LibraryPanel(QWidget):
    entry_open_requested = Signal(int)       # entry id
    entry_rename_requested = Signal(int)     # entry id (UI 상에서 인라인 편집 시작 요청)
    entry_delete_requested = Signal(int)     # entry id — 휴지통으로 (Shift+Del / 메뉴)
    entry_remove_requested = Signal(int)     # entry id — 라이브러리에서만 제외 (Del)
    entry_open_folder_requested = Signal(int)  # entry id
    entry_undelete_requested = Signal()       # Ctrl+Z — 마지막 삭제 항목 복원
    # 외부 파일 드롭 → 라이브러리에 추가 (탭 자동 열림 없음). MainWindow 가 받아 처리.
    files_dropped_for_library = Signal(list)   # list[str] — 절대 경로

    _ACCEPTED_DROP_EXTS = {
        ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".wmv", ".gif",
        ".png", ".jpg", ".jpeg",
        ".md", ".markdown",
    }

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
        # PySide6 — delegate Python 참조 유지 필수. 인스턴스 속성으로 보관해야 GC 안 됨.
        self._item_delegate = _TwoLineDelegate(self.list_widget)
        self.list_widget.setItemDelegate(self._item_delegate)
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

        # 외부 파일 드롭 수락 — 라이브러리에만 추가 (탭 열림 X). 자식 list_widget 도
        # viewport drop 이 부모에 전파되도록 viewport.setAcceptDrops(False).
        self.setAcceptDrops(True)
        try:
            self.list_widget.viewport().setAcceptDrops(False)
        except (RuntimeError, AttributeError):
            pass
        # 드래그-드롭 hint — 패널 위 호버 시 표시되는 안내 라벨 (영역별 hint).
        self._drop_hint = QLabel("📋 여기에 놓으면 라이브러리에 추가됩니다", self)
        self._drop_hint.setStyleSheet(
            "background: rgba(59, 130, 246, 230); color: white;"
            " padding: 6px 14px; border-radius: 8px; font-weight: bold;"
        )
        self._drop_hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._drop_hint.hide()

    # ---------- 모델 → UI ----------
    def _insert(self, entry: LibraryEntry, *, at_top: bool) -> None:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, entry.id)
        item.setData(Qt.UserRole + 1, entry.kind)
        item.setData(_ROLE_FOLDER, self._render_folder(entry))
        item.setText(self._render_text(entry))
        item.setToolTip(self._render_tooltip(entry))
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        if not entry.thumbnail.isNull():
            # FastTransformation — 48×32 icon 에 SmoothTransformation 의 차이는 인지
            # 불가능하지만 대량 갱신 시 메인 스레드 비용 크게 절감.
            item.setIcon(QIcon(QPixmap.fromImage(entry.thumbnail).scaled(
                48, 32, Qt.KeepAspectRatio, Qt.FastTransformation
            )))
        if at_top:
            self.list_widget.insertItem(0, item)
        else:
            self.list_widget.addItem(item)
        self._items_by_id[entry.id] = item
        if self._mode is not None:
            wanted = self._kind_for_mode(self._mode.mode())
            item.setHidden(entry.kind is not wanted)
        # 드롭으로 추가된 항목이 즉시 보이도록 viewport 강제 갱신 — 안 그러면 다음
        # 모드 전환(_refresh_visibility)까지 새 항목이 안 그려지는 경우가 있었음.
        self.list_widget.viewport().update()

    # 종류별 라벨 prefix. EntryKind.SCREENSHOT 은 IMAGE 의 별칭(값이 같음)이라
    # `is` 비교가 위험 → VIDEO/DOCUMENT 를 먼저 거르고 나머지를 이미지로 처리.
    @staticmethod
    def _prefix_for_kind(kind: "EntryKind") -> str:
        if kind is EntryKind.VIDEO:
            return "🎞"
        if kind is EntryKind.DOCUMENT:
            return "📄"
        return "📸"

    @staticmethod
    def _render_text(entry: LibraryEntry) -> str:
        prefix = LibraryPanel._prefix_for_kind(entry.kind)
        if entry.display_name:
            base = entry.display_name
        else:
            ts = entry.created_at.strftime("%H:%M")
            base = f"{entry.source_label} {ts}"
        suffix = _format_duration(entry.duration_ms) if entry.kind is EntryKind.VIDEO else ""
        return f"{prefix} {base}{suffix}"

    @staticmethod
    def _render_folder(entry: LibraryEntry) -> str:
        """윗줄에 표시할 부모 폴더 경로. path 없으면 빈 문자열."""
        if entry.path is None:
            return ""
        try:
            return str(entry.path.parent)
        except Exception:
            return ""

    @staticmethod
    def _render_tooltip(entry: LibraryEntry) -> str:
        """툴팁 — 전체 경로(있으면) 우선, 없으면 표시명."""
        if entry.path is not None:
            return str(entry.path)
        return entry.display_name or entry.source_label

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
            item.setData(_ROLE_FOLDER, self._render_folder(entry))
            item.setToolTip(self._render_tooltip(entry))
            if not entry.thumbnail.isNull():
                item.setIcon(QIcon(QPixmap.fromImage(entry.thumbnail).scaled(
                    48, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )))
        finally:
            self.list_widget.blockSignals(False)

    # ---------- UI → 외부 ----------
    # ---------- 외부 파일 드래그-드롭 (라이브러리에만 추가) ----------
    def _accepted_paths(self, mime) -> list[str]:
        """mime data 에서 수락 가능한 파일 절대 경로만 추출. 빈 리스트면 거부."""
        if not mime.hasUrls():
            return []
        out: list[str] = []
        for u in mime.urls():
            if not u.isLocalFile():
                continue
            p = _Path(u.toLocalFile())
            if not p.is_file():
                continue
            if p.suffix.lower() in self._ACCEPTED_DROP_EXTS:
                out.append(str(p))
        return out

    def _show_drop_hint(self, event_pos: QPoint) -> None:
        """드래그 중 마우스 옆 hint 라벨 표시. 위치는 마우스 아래."""
        self._drop_hint.adjustSize()
        x = max(8, min(self.width() - self._drop_hint.width() - 8,
                       event_pos.x() + 16))
        y = max(8, min(self.height() - self._drop_hint.height() - 8,
                       event_pos.y() + 20))
        self._drop_hint.move(x, y)
        self._drop_hint.raise_()
        self._drop_hint.show()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._accepted_paths(event.mimeData()):
            event.acceptProposedAction()
            self._show_drop_hint(event.position().toPoint())
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._accepted_paths(event.mimeData()):
            event.acceptProposedAction()
            self._show_drop_hint(event.position().toPoint())
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._drop_hint.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._drop_hint.hide()
        paths = self._accepted_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        self.files_dropped_for_library.emit(paths)
        event.acceptProposedAction()

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
        # prefix 제거: "📸 " / "🎞 " / "📄 " 로 시작
        for pfx in ("📸 ", "🎞 ", "📄 "):
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
                        # Shift+Del → 휴지통, Del 단독 → 라이브러리에서만 제외.
                        if event.modifiers() & Qt.ShiftModifier:
                            self.entry_delete_requested.emit(int(eid))
                        else:
                            self.entry_remove_requested.emit(int(eid))
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
        remove_action = QAction("라이브러리에서 제외 (Del)", self)
        remove_action.triggered.connect(
            lambda: self.entry_remove_requested.emit(eid)
        )
        menu.addAction(remove_action)
        delete_action = QAction("삭제 — 휴지통으로 (Shift+Del)", self)
        delete_action.triggered.connect(
            lambda: self.entry_delete_requested.emit(eid)
        )
        menu.addAction(delete_action)

        menu.exec(self.list_widget.viewport().mapToGlobal(pos))

    def _refresh_visibility(self, mode: AppMode) -> None:
        # 항목 N 개에 대해 setHidden 호출 시 Qt 가 매번 layout invalidate 할 수 있어
        # setUpdatesEnabled(False) 로 paint 일괄 처리. 모드 전환 시 버벅임 방지.
        wanted = self._kind_for_mode(mode)
        self.list_widget.setUpdatesEnabled(False)
        try:
            for i in range(self.list_widget.count()):
                it = self.list_widget.item(i)
                kind = it.data(Qt.UserRole + 1)
                it.setHidden(kind is not wanted)
        finally:
            self.list_widget.setUpdatesEnabled(True)

    @staticmethod
    def _kind_for_mode(mode: AppMode) -> "Optional[EntryKind]":
        if mode is AppMode.VIDEO:
            return EntryKind.VIDEO
        if mode is AppMode.DOCUMENT:
            return EntryKind.DOCUMENT
        return EntryKind.SCREENSHOT
