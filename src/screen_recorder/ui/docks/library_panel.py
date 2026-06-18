"""라이브러리 패널 — 세션 결과물 썸네일 목록 (모드별 필터링 + 컨텍스트 메뉴)."""
from __future__ import annotations
from typing import Optional

from pathlib import Path as _Path

from PySide6.QtCore import Qt, Signal, QSize, QPoint, QEvent, QRect, QMimeData, QUrl
from PySide6.QtGui import (
    QPixmap, QIcon, QAction, QPainter, QFont, QFontMetrics, QColor, QDrag,
    QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QLabel, QMenu,
    QProxyStyle, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QApplication,
)


_ROLE_MISSING = Qt.UserRole + 3   # 외부에서 파일이 삭제됨 → 취소선 + ✕ 표시 (Phase 60)
_MISSING_COLOR = "#d08770"        # 취소선/dim/✕ 색
_X_BTN_SIZE = 16
_X_BTN_RIGHT_PAD = 6


def _x_button_rect(row_rect: "QRect") -> "QRect":
    """삭제된 항목 오른쪽 끝의 ✕ 클릭/그리기 영역 (행 rect 기준). delegate 와 히트테스트가 공유."""
    top = row_rect.top() + (row_rect.height() - _X_BTN_SIZE) // 2
    return QRect(row_rect.right() - _X_BTN_SIZE - _X_BTN_RIGHT_PAD, top,
                 _X_BTN_SIZE, _X_BTN_SIZE)


class _DragOutListWidget(QListWidget):
    """라이브러리 항목을 파일 URL 로 드래그아웃(비교 뷰 등 외부 칸으로). 외부→라이브러리
    드롭은 부모 LibraryPanel 이 처리(여기선 드래그 *시작*만 담당)."""

    def __init__(self, path_for_item, on_x_clicked=None) -> None:
        super().__init__()
        self._path_for_item = path_for_item
        self._on_x_clicked = on_x_clicked   # 삭제된 항목 ✕ 클릭 → entry_id 콜백
        self.setDragEnabled(True)

    def mousePressEvent(self, e) -> None:  # type: ignore[override]
        # 삭제된(취소선) 항목의 오른쪽 ✕ 클릭이면 제거 콜백 후 소비 — 선택/열기/드래그로
        # 새지 않게 한다(히트테스트가 결정적이라 editorEvent 경로보다 안전).
        item = self.itemAt(e.position().toPoint())
        if item is not None and item.data(_ROLE_MISSING):
            if _x_button_rect(self.visualItemRect(item)).contains(e.position().toPoint()):
                eid = item.data(Qt.UserRole)
                if eid is not None and self._on_x_clicked is not None:
                    self._on_x_clicked(int(eid))
                e.accept()
                return
        super().mousePressEvent(e)

    def mime_for_item(self, item) -> "QMimeData | None":
        p = self._path_for_item(item) if item is not None else None
        if p is None:
            return None
        m = QMimeData()
        m.setUrls([QUrl.fromLocalFile(str(p))])
        return m

    def startDrag(self, supportedActions) -> None:  # type: ignore[override]
        mime = self.mime_for_item(self.currentItem())
        if mime is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


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

        # 2. 아이콘. 썸네일 없는 문서(.md) 항목은 아이콘 칸(48px)을 0 폭으로 접어
        #    텍스트를 왼쪽 끝에 붙인다 — 빈 썸네일 플레이스홀더 제거.
        icon = index.data(Qt.DecorationRole)
        has_icon = icon is not None and not icon.isNull()
        icon_w = option.decorationSize.width() if has_icon else 0
        icon_h = option.decorationSize.height()
        icon_rect = QRect(rect.left(),
                          rect.top() + (rect.height() - icon_h) // 2,
                          icon_w, icon_h)
        if has_icon:
            icon.paint(painter, icon_rect, Qt.AlignCenter)

        # 3. 텍스트 영역. 아이콘이 있을 때만 아이콘+gap 만큼 들여쓰고, 없으면 왼쪽 끝.
        text_left = (icon_rect.right() + self._ICON_TEXT_GAP) if has_icon else rect.left()
        text_rect = QRect(text_left, rect.top(),
                          max(0, rect.right() - text_left), rect.height())

        folder = index.data(_ROLE_FOLDER) or ""
        filename = index.data(Qt.DisplayRole) or ""

        # 외부 삭제된 항목 — 파일명 취소선 + dim + 오른쪽 ✕. ✕ 영역만큼 텍스트 폭을 줄여
        # 글자가 ✕ 위에 겹치지 않게 한다.
        missing = bool(index.data(_ROLE_MISSING))
        if missing:
            text_rect = QRect(
                text_rect.left(), text_rect.top(),
                max(0, text_rect.width() - (_X_BTN_SIZE + _X_BTN_RIGHT_PAD + 4)),
                text_rect.height(),
            )

        if option.state & QStyle.State_Selected:
            base_color = option.palette.highlightedText().color()
        else:
            base_color = option.palette.text().color()

        # 파일명 전용 폰트/색 — 삭제 시 취소선 + (비선택 시) dim 색.
        name_font = QFont(option.font)
        if missing:
            name_font.setStrikeOut(True)
        if missing and not (option.state & QStyle.State_Selected):
            name_color = QColor(_MISSING_COLOR)
        else:
            name_color = base_color

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

            painter.setFont(name_font)
            painter.setPen(name_color)
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
            painter.setFont(name_font)
            painter.setPen(name_color)
            name_elided = name_fm.elidedText(
                filename, Qt.ElideRight, text_rect.width()
            )
            painter.drawText(text_rect.left(), top + name_fm.ascent(), name_elided)

        # 오른쪽 끝 ✕ — 삭제된 항목 정리 버튼(클릭은 _DragOutListWidget 히트테스트).
        if missing:
            x_rect = _x_button_rect(option.rect)
            painter.setFont(option.font)
            painter.setPen(QColor(_MISSING_COLOR))
            painter.drawText(x_rect, Qt.AlignCenter, "✕")

        painter.restore()


def _format_duration(ms: int) -> str:
    s = max(0, ms // 1000)
    return f" ({s}s)" if s < 60 else f" ({s // 60}m{s % 60:02d}s)"


class LibraryPanel(QWidget):
    entry_open_requested = Signal(int)       # entry id
    entry_rename_requested = Signal(int)     # entry id (UI 상에서 인라인 편집 시작 요청)
    entry_delete_requested = Signal(int)     # entry id — 휴지통으로 (Shift+Del / 메뉴)
    entry_remove_requested = Signal(int)     # entry id — 라이브러리에서만 삭제, 디스크 유지 (Del)
    entry_open_folder_requested = Signal(int)  # entry id
    entry_undelete_requested = Signal()       # Ctrl+Z — 마지막 삭제 항목 복원
    # 외부 파일 드롭 → 라이브러리에 추가 (탭 자동 열림 없음). MainWindow 가 받아 처리.
    files_dropped_for_library = Signal(list)   # list[str] — 절대 경로

    _ACCEPTED_DROP_EXTS = {
        ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".wmv", ".gif",
        ".png", ".jpg", ".jpeg",
        ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
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

        self.list_widget = _DragOutListWidget(self._path_for_item, self._on_x_remove_clicked)
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
        model.entry_missing_changed.connect(self._on_entry_missing)

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
        item.setData(_ROLE_MISSING, bool(getattr(entry, "missing", False)))
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
            item.setHidden(
                not self._is_visible_in_mode(entry.kind, self._mode.mode()))
        # 드롭으로 추가된 항목이 즉시 보이도록 viewport 강제 갱신 — 안 그러면 다음
        # 모드 전환(_refresh_visibility)까지 새 항목이 안 그려지는 경우가 있었음.
        self.list_widget.viewport().update()

    # 종류별 라벨 prefix. EntryKind.SCREENSHOT 은 IMAGE 의 별칭(값이 같음)이라
    # `is` 비교가 위험 → VIDEO/DOCUMENT 를 먼저 거르고 나머지를 이미지로 처리.
    @staticmethod
    def _prefix_for_kind(kind: "EntryKind") -> str:
        if kind is EntryKind.VIDEO:
            return "🎞"
        if kind is EntryKind.AUDIO:
            return "🎵"
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

    def _on_entry_missing(self, entry_id: int, missing: bool) -> None:
        """모델이 외부 삭제/복구를 알림 → 항목에 취소선(+✕) 토글 후 repaint."""
        item = self._items_by_id.get(entry_id)
        if item is None:
            return
        item.setData(_ROLE_MISSING, bool(missing))
        self.list_widget.viewport().update()

    def _on_x_remove_clicked(self, entry_id: int) -> None:
        """삭제된 항목의 ✕ 클릭 → 라이브러리에서 제거 + 열린 탭 닫기(기존 remove 경로 재사용)."""
        self.entry_remove_requested.emit(int(entry_id))

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

    # ---------- 항목 드래그아웃 (비교 뷰 등 외부 칸으로) ----------
    def _path_for_item(self, item) -> "Optional[_Path]":
        """list item → 그 항목의 파일 경로(없으면 None — 드래그 안 함)."""
        if item is None:
            return None
        eid = item.data(Qt.UserRole)
        if eid is None:
            return None
        entry = self._model.get(int(eid))
        if entry is None or entry.path is None:
            return None
        return entry.path

    def _mime_for_item(self, item) -> "Optional[QMimeData]":
        """드래그 mime(파일 URL) 빌더 — list_widget 에 위임(테스트/외부용)."""
        return self.list_widget.mime_for_item(item)

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

    def _is_own_drag(self, event) -> bool:
        # 자기 항목을 드래그아웃하다 패널 위로 돌아온 경우 — 라이브러리에 재추가하지 않는다.
        return event.source() is self.list_widget

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if not self._is_own_drag(event) and self._accepted_paths(event.mimeData()):
            event.acceptProposedAction()
            self._show_drop_hint(event.position().toPoint())
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if not self._is_own_drag(event) and self._accepted_paths(event.mimeData()):
            event.acceptProposedAction()
            self._show_drop_hint(event.position().toPoint())
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._drop_hint.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._drop_hint.hide()
        if self._is_own_drag(event):
            event.ignore()
            return
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
                        # Shift+Del → 휴지통, Del 단독 → 라이브러리에서만 삭제(디스크 유지).
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
        menu = self._build_context_menu(item, int(eid))
        menu.exec(self.list_widget.viewport().mapToGlobal(pos))

    def _build_context_menu(self, item: QListWidgetItem, eid: int) -> QMenu:
        """우클릭 메뉴 구성 (exec 분리 → 테스트 가능).

        파괴적 항목은 사용자 혼동을 막기 위해 문구를 또렷이 가른다:
        '라이브러리에서만 삭제'(디스크 파일 유지) vs '휴지통에 넣기'(파일 이동).
        """
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        rename_action = QAction("이름 바꾸기 (F2)", self)
        rename_action.triggered.connect(lambda: self.list_widget.editItem(item))
        menu.addAction(rename_action)

        open_folder_action = QAction("저장 폴더 열기", self)
        open_folder_action.triggered.connect(
            lambda: self.entry_open_folder_requested.emit(eid)
        )
        menu.addAction(open_folder_action)

        menu.addSeparator()
        # 목록에서만 빼는 비파괴 동작 — 디스크 파일은 건드리지 않는다.
        remove_action = QAction("라이브러리에서만 삭제 (Del)", self)
        remove_action.setToolTip("목록에서만 빼고, 디스크 파일은 그대로 둡니다.")
        remove_action.triggered.connect(
            lambda: self.entry_remove_requested.emit(eid)
        )
        menu.addAction(remove_action)
        # 실제 파일을 휴지통으로 보내는 파괴적 동작 (Ctrl+Z 로 복원).
        delete_action = QAction("휴지통에 넣기 (Shift+Del)", self)
        delete_action.setToolTip("디스크 파일을 휴지통으로 보냅니다 (Ctrl+Z 로 복원).")
        delete_action.triggered.connect(
            lambda: self.entry_delete_requested.emit(eid)
        )
        menu.addAction(delete_action)
        return menu

    def _refresh_visibility(self, mode: AppMode) -> None:
        # 항목 N 개에 대해 setHidden 호출 시 Qt 가 매번 layout invalidate 할 수 있어
        # setUpdatesEnabled(False) 로 paint 일괄 처리. 모드 전환 시 버벅임 방지.
        self.list_widget.setUpdatesEnabled(False)
        try:
            for i in range(self.list_widget.count()):
                it = self.list_widget.item(i)
                kind = it.data(Qt.UserRole + 1)
                it.setHidden(not self._is_visible_in_mode(kind, mode))
        finally:
            self.list_widget.setUpdatesEnabled(True)

    @staticmethod
    def _kind_for_mode(mode: AppMode) -> "Optional[EntryKind]":
        if mode is AppMode.VIDEO:
            return EntryKind.VIDEO
        if mode is AppMode.DOCUMENT:
            return EntryKind.DOCUMENT
        return EntryKind.SCREENSHOT

    @staticmethod
    def _is_visible_in_mode(kind: "EntryKind", mode: AppMode) -> bool:
        """이 종류가 현재 모드 라이브러리에 보여야 하는지.

        오디오(AUDIO)는 영상 모드 라이브러리에 영상과 함께 표시(전용 오디오 탭도
        AppMode.VIDEO 영역에 살기 때문)."""
        if kind is LibraryPanel._kind_for_mode(mode):
            return True
        if mode is AppMode.VIDEO and kind is EntryKind.AUDIO:
            return True
        return False
