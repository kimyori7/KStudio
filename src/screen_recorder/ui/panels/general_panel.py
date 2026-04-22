"""녹화(일반) 설정 패널 — 출력 폴더, 파일명, 모드 + 출력 파일 리스트."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QFileSystemWatcher, QUrl, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout,
    QRadioButton, QButtonGroup, QFileDialog, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView,
)

from ...core.settings import GeneralSettings


_RECORDING_EXTS = {".mp4", ".mkv", ".webm", ".gif", ".mov", ".avi"}


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
        self.file_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.setAlternatingRowColors(True)
        header = self.file_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.file_table.itemDoubleClicked.connect(lambda _item: self._open_selected())
        self.file_table.itemSelectionChanged.connect(self._update_buttons)
        root.addWidget(self.file_table, stretch=1)

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
        return Path.home() / "Videos" / "ScreenRecorder"

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
            time_item = QTableWidgetItem(
                datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
            )
            name_item = QTableWidgetItem(p.name)
            name_item.setData(Qt.UserRole, str(p))
            # 툴팁으로 전체 경로 노출
            name_item.setToolTip(str(p))
            self.file_table.setItem(row, 0, name_item)
            self.file_table.setItem(row, 1, size_item)
            self.file_table.setItem(row, 2, time_item)
        self._update_buttons()

    def _selected_path(self) -> Path | None:
        row = self.file_table.currentRow()
        if row < 0:
            return None
        item = self.file_table.item(row, 0)
        if item is None:
            return None
        path_str = item.data(Qt.UserRole)
        return Path(path_str) if path_str else None

    def _update_buttons(self) -> None:
        has_sel = self._selected_path() is not None
        self.open_btn.setEnabled(has_sel)
        self.delete_btn.setEnabled(has_sel)

    def _open_selected(self) -> None:
        p = self._selected_path()
        if p is None or not p.exists():
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _delete_selected(self) -> None:
        p = self._selected_path()
        if p is None:
            return
        ret = QMessageBox.question(
            self, "삭제 확인",
            f"다음 파일을 삭제할까요?\n\n{p.name}\n\n휴지통이 아니라 영구 삭제입니다.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        try:
            p.unlink()
        except OSError as e:
            QMessageBox.warning(self, "삭제 실패", f"{p.name}\n\n{e}")
            return
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
