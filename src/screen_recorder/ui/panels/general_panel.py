"""녹화(일반) 설정 패널 — 출력 폴더, 파일명, 모드 + 출력 파일 리스트."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

import logging

from PySide6.QtCore import Qt, Signal, QFileSystemWatcher, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout,
    QRadioButton, QButtonGroup, QFileDialog, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QStyledItemDelegate,
)

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None

from ...core.settings import GeneralSettings
from ..toast import show_toast


_RECORDING_EXTS = {".mp4", ".mkv", ".webm", ".gif", ".mov", ".avi"}


class _FilenameStemSelectDelegate(QStyledItemDelegate):
    """편집 진입 시 확장자를 제외한 파일명 본문(stem)만 선택 — Windows 탐색기와 동일."""

    def setEditorData(self, editor, index):
        super().setEditorData(editor, index)
        if isinstance(editor, QLineEdit):
            text = editor.text()
            dot = text.rfind(".")
            stem_len = dot if dot > 0 else len(text)
            # 부모 구현이 selectAll을 한 뒤이므로 한 틱 뒤에 stem 만 선택
            QTimer.singleShot(0, lambda: editor.setSelection(0, stem_len))


class GeneralPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: GeneralSettings):
        super().__init__()
        self.settings = settings

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---------- 폼 (출력 폴더 / 파일명 / 모드) ----------
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        root.addLayout(form)

        dir_row = QWidget()
        dir_layout = QHBoxLayout(dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        self.dir_edit = QLineEdit(settings.output_dir)
        browse = QPushButton("📁")
        browse.setFixedWidth(36)
        browse.clicked.connect(self._browse)
        dir_layout.addWidget(self.dir_edit, stretch=1)
        dir_layout.addWidget(browse)
        form.addRow("출력 폴더:", dir_row)

        self.pattern_edit = QLineEdit(settings.filename_pattern)
        form.addRow("파일명:", self.pattern_edit)

        mode_row = QWidget()
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.video_radio = QRadioButton("영상")
        self.gif_radio = QRadioButton("GIF")
        if settings.mode == "gif":
            self.gif_radio.setChecked(True)
        else:
            self.video_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.video_radio)
        group.addButton(self.gif_radio)
        mode_layout.addWidget(self.video_radio)
        mode_layout.addWidget(self.gif_radio)
        mode_layout.addStretch(1)
        form.addRow("모드:", mode_row)

        # ---------- 구분선 + "녹화 파일" 헤더 ----------
        sep = QLabel()
        sep.setFrameShape(QLabel.HLine)
        sep.setStyleSheet("color: #ccc;")
        root.addWidget(sep)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("📂 <b>녹화 파일</b>"))
        header_row.addStretch(1)
        self.refresh_btn = QPushButton("🔄 새로고침")
        self.refresh_btn.clicked.connect(self._refresh)
        header_row.addWidget(self.refresh_btn)
        root.addLayout(header_row)

        # ---------- 파일 테이블 ----------
        self.file_table = QTableWidget(0, 3)
        self.file_table.setHorizontalHeaderLabels(["파일명", "용량", "시간"])
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # 선택된 셀을 다시 클릭(탐색기 식) + F2 키로 편집 진입.
        # 더블클릭은 _open_selected 가 먼저 잡으므로 편집과 충돌하지 않음.
        self.file_table.setEditTriggers(
            QAbstractItemView.SelectedClicked | QAbstractItemView.EditKeyPressed
        )
        self.file_table.setAlternatingRowColors(True)
        header = self.file_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.file_table.itemDoubleClicked.connect(lambda _item: self._open_selected())
        self.file_table.itemSelectionChanged.connect(self._update_buttons)
        self.file_table.itemChanged.connect(self._on_item_changed)
        # 0번 컬럼 편집기에 stem 선택 delegate 적용
        self._filename_delegate = _FilenameStemSelectDelegate(self.file_table)
        self.file_table.setItemDelegateForColumn(0, self._filename_delegate)
        root.addWidget(self.file_table, stretch=1)

        # Del / F2 단축키 (테이블에 포커스 있을 때만)
        del_shortcut = QShortcut(QKeySequence(Qt.Key_Delete), self.file_table)
        del_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        del_shortcut.activated.connect(self._delete_selected)

        rename_shortcut = QShortcut(QKeySequence(Qt.Key_F2), self.file_table)
        rename_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        rename_shortcut.activated.connect(self._begin_rename)

        # ---------- 동작 버튼 ----------
        btn_row = QHBoxLayout()
        self.open_btn = QPushButton("▶ 열기")
        self.open_btn.clicked.connect(self._open_selected)
        self.delete_btn = QPushButton("🗑 삭제")
        self.delete_btn.clicked.connect(self._delete_selected)
        self.folder_btn = QPushButton("📁 폴더 열기")
        self.folder_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(self.open_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.folder_btn)
        root.addLayout(btn_row)

        # ---------- 시그널 ----------
        self.dir_edit.editingFinished.connect(self._sync)
        self.pattern_edit.editingFinished.connect(self._sync)
        self.video_radio.toggled.connect(self._sync)
        self.gif_radio.toggled.connect(self._sync)

        # ---------- 파일시스템 감시 ----------
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._schedule_refresh)
        # 파일 저장 직후 연달아 이벤트가 오는 걸 합쳐 처리하기 위한 딜레이
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self._refresh)

        self._rewatch()
        self._update_buttons()

    # ---------- 녹화 상태 ----------

    def set_recording(self, recording: bool) -> None:
        """녹화 중에는 출력 설정(모드/폴더/파일명) 변경 잠금."""
        self.video_radio.setEnabled(not recording)
        self.gif_radio.setEnabled(not recording)
        self.dir_edit.setEnabled(not recording)
        self.pattern_edit.setEnabled(not recording)

    # ---------- 설정 ----------

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "출력 폴더", self.dir_edit.text())
        if path:
            self.dir_edit.setText(path)
            self._sync()

    def _sync(self) -> None:
        old = self.settings.output_dir
        self.settings.output_dir = self.dir_edit.text()
        self.settings.filename_pattern = self.pattern_edit.text()
        self.settings.mode = "gif" if self.gif_radio.isChecked() else "video"
        self.settings_changed.emit()
        if self.settings.output_dir != old:
            self._rewatch()

    # ---------- 파일 리스트 ----------

    def _resolve_output_dir(self) -> Path:
        if self.settings.output_dir:
            return Path(self.settings.output_dir)
        return Path.home() / "Videos" / "KStudio"

    def _rewatch(self) -> None:
        existing = self._watcher.directories()
        if existing:
            self._watcher.removePaths(existing)
        path = self._resolve_output_dir()
        if path.exists():
            self._watcher.addPath(str(path))
        self._refresh()

    def _schedule_refresh(self, _path: str) -> None:
        self._refresh_timer.start()

    def _refresh(self) -> None:
        path = self._resolve_output_dir()
        # itemChanged 콜백이 _refresh 도중 트리거되지 않도록 잠시 차단
        self.file_table.blockSignals(True)
        try:
            self.file_table.setRowCount(0)
            if not path.exists():
                return
            try:
                files = [
                    p for p in path.iterdir()
                    if p.is_file() and p.suffix.lower() in _RECORDING_EXTS
                ]
            except OSError:
                return
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            self.file_table.setRowCount(len(files))
            for row, p in enumerate(files):
                try:
                    st = p.stat()
                except OSError:
                    continue
                size_item = QTableWidgetItem(_format_size(st.st_size))
                size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                size_item.setFlags(size_item.flags() & ~Qt.ItemIsEditable)
                time_item = QTableWidgetItem(
                    datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                )
                time_item.setFlags(time_item.flags() & ~Qt.ItemIsEditable)
                name_item = QTableWidgetItem(p.name)
                name_item.setData(Qt.UserRole, str(p))
                # 툴팁으로 전체 경로 노출
                name_item.setToolTip(str(p))
                # 0번 컬럼만 편집 허용
                name_item.setFlags(name_item.flags() | Qt.ItemIsEditable)
                self.file_table.setItem(row, 0, name_item)
                self.file_table.setItem(row, 1, size_item)
                self.file_table.setItem(row, 2, time_item)
        finally:
            self.file_table.blockSignals(False)
        self._update_buttons()

    def _selected_paths(self) -> list[Path]:
        rows = sorted({idx.row() for idx in self.file_table.selectedIndexes()})
        paths: list[Path] = []
        for row in rows:
            item = self.file_table.item(row, 0)
            if item is None:
                continue
            path_str = item.data(Qt.UserRole)
            if path_str:
                paths.append(Path(path_str))
        return paths

    def _update_buttons(self) -> None:
        sel = self._selected_paths()
        n = len(sel)
        # 열기는 단수 선택일 때만 (여러 개 동시 열기는 혼란스러움)
        self.open_btn.setEnabled(n == 1)
        self.delete_btn.setEnabled(n >= 1)
        if n > 1:
            self.delete_btn.setText(f"🗑 삭제 ({n})")
        else:
            self.delete_btn.setText("🗑 삭제")

    def _open_selected(self) -> None:
        sel = self._selected_paths()
        if len(sel) != 1:
            return
        p = sel[0]
        if not p.exists():
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _begin_rename(self) -> None:
        """F2 키로 호출. 현재 행의 파일명 셀을 편집 모드로 진입."""
        row = self.file_table.currentRow()
        if row < 0:
            return
        item = self.file_table.item(row, 0)
        if item is not None:
            self.file_table.editItem(item)

    def _on_item_changed(self, item) -> None:
        """파일명 셀이 편집되어 변경되었을 때 실제 파일을 rename."""
        if item.column() != 0:
            return
        old_path_str = item.data(Qt.UserRole)
        if not old_path_str:
            return
        old_path = Path(old_path_str)
        new_name = item.text().strip()
        host = self.window() or self

        def revert():
            self.file_table.blockSignals(True)
            try:
                item.setText(old_path.name)
            finally:
                self.file_table.blockSignals(False)

        if not new_name or new_name == old_path.name:
            revert()
            return
        invalid_chars = set('\\/:*?"<>|')
        if any(c in invalid_chars for c in new_name) or new_name in {".", ".."}:
            show_toast(host, '이름에 \\ / : * ? " < > | 는 사용할 수 없습니다.', 1500)
            revert()
            return

        new_path = old_path.parent / new_name
        if new_path.exists():
            show_toast(host, f"'{new_name}' 이름이 이미 있습니다.", 1500)
            revert()
            return
        try:
            old_path.rename(new_path)
        except OSError as e:
            logging.getLogger(__name__).warning("rename %s -> %s failed: %s", old_path, new_path, e)
            show_toast(host, f"이름 바꾸기 실패: {e}", 1500)
            revert()
            return
        # 성공 — UserRole에 새 경로 + 툴팁 갱신
        self.file_table.blockSignals(True)
        try:
            item.setData(Qt.UserRole, str(new_path))
            item.setToolTip(str(new_path))
        finally:
            self.file_table.blockSignals(False)
        show_toast(host, f"'{new_name}' (으)로 이름 변경", 1000)

    def _delete_selected(self) -> None:
        sel = self._selected_paths()
        if not sel:
            return
        host = self.window() or self
        if send2trash is None:
            show_toast(host, "삭제 실패: send2trash 라이브러리가 없습니다.", 1500)
            return

        failed: list[tuple[Path, str]] = []
        for p in sel:
            try:
                send2trash(str(p))
            except Exception as e:
                logging.getLogger(__name__).warning("send2trash failed for %s: %s", p, e)
                failed.append((p, str(e)))

        ok_count = len(sel) - len(failed)
        if ok_count and not failed:
            if ok_count == 1:
                show_toast(host, f"'{sel[0].name}' 휴지통으로 들어갑니다.", 1000)
            else:
                show_toast(host, f"{ok_count}개 파일이 휴지통으로 들어갑니다.", 1000)
        elif ok_count and failed:
            show_toast(host, f"{ok_count}개 이동 완료, {len(failed)}개 실패.", 1500)
        else:
            show_toast(host, f"삭제 실패: {failed[0][1]}", 1500)
        self._refresh()

    def _open_folder(self) -> None:
        path = self._resolve_output_dir()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
