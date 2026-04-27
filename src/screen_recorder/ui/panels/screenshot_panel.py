"""저장 / 파일명 설정 패널 — 이미지·영상 저장 폴더와 파일명 패턴.

(이름은 ScreenshotPanel 로 유지 — PreferencesDialog 호환. 실제 역할은 더 넓다.)
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout,
    QFileDialog, QGroupBox, QComboBox,
)

from ...core.settings import ScreenshotSettings, GeneralSettings


_FORMAT_LABELS = [("png", "PNG")]


class ScreenshotPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, screenshot: ScreenshotSettings,
                 general: GeneralSettings | None = None):
        super().__init__()
        self.settings = screenshot          # 이미지 (스크린샷)
        self._general = general             # 영상 — 없으면 영상 섹션 숨김

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # ---------- 이미지 저장 ----------
        img_box = QGroupBox("📸 이미지 저장")
        img_form = QFormLayout(img_box)
        img_form.setLabelAlignment(Qt.AlignRight)

        self.img_dir_edit, img_dir_row = self._make_dir_row(
            screenshot.save_dir, "_browse_image_dir"
        )
        img_form.addRow("저장 폴더:", img_dir_row)

        self.img_pattern_edit = QLineEdit(screenshot.filename_pattern)
        self.img_pattern_edit.setToolTip(
            "사용 가능 토큰: {date}, {time}, {datetime}, {target}, {mode} 등"
        )
        img_form.addRow("파일명:", self.img_pattern_edit)

        self.img_format_combo = QComboBox()
        for key, label in _FORMAT_LABELS:
            self.img_format_combo.addItem(label, key)
        cur = screenshot.format
        for i in range(self.img_format_combo.count()):
            if self.img_format_combo.itemData(i) == cur:
                self.img_format_combo.setCurrentIndex(i)
                break
        img_form.addRow("형식:", self.img_format_combo)

        root.addWidget(img_box)

        # ---------- 영상 저장 ----------
        if general is not None:
            vid_box = QGroupBox("🎞 영상 저장")
            vid_form = QFormLayout(vid_box)
            vid_form.setLabelAlignment(Qt.AlignRight)

            self.vid_dir_edit, vid_dir_row = self._make_dir_row(
                general.output_dir, "_browse_video_dir"
            )
            vid_form.addRow("저장 폴더:", vid_dir_row)

            self.vid_pattern_edit = QLineEdit(general.filename_pattern)
            self.vid_pattern_edit.setToolTip(
                "사용 가능 토큰: {date}, {time}, {datetime}, {target}, {mode} 등"
            )
            vid_form.addRow("파일명:", self.vid_pattern_edit)

            root.addWidget(vid_box)

            self.vid_dir_edit.editingFinished.connect(self._sync)
            self.vid_pattern_edit.editingFinished.connect(self._sync)

        root.addStretch(1)

        # ---------- 시그널 ----------
        self.img_dir_edit.editingFinished.connect(self._sync)
        self.img_pattern_edit.editingFinished.connect(self._sync)
        self.img_format_combo.currentIndexChanged.connect(self._sync)

    # ---------- helper ----------

    def _make_dir_row(self, initial: str, browse_method: str):
        edit = QLineEdit(initial)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton("📁")
        browse.setFixedWidth(36)
        browse.clicked.connect(getattr(self, browse_method))
        layout.addWidget(edit, stretch=1)
        layout.addWidget(browse)
        return edit, row

    def _browse_image_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "이미지 저장 폴더", self.img_dir_edit.text() or str(Path.home())
        )
        if path:
            self.img_dir_edit.setText(path)
            self._sync()

    def _browse_video_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "영상 저장 폴더", self.vid_dir_edit.text() or str(Path.home())
        )
        if path:
            self.vid_dir_edit.setText(path)
            self._sync()

    def _sync(self) -> None:
        self.settings.save_dir = self.img_dir_edit.text()
        self.settings.filename_pattern = self.img_pattern_edit.text()
        fmt = self.img_format_combo.currentData()
        if fmt:
            self.settings.format = fmt

        if self._general is not None:
            self._general.output_dir = self.vid_dir_edit.text()
            self._general.filename_pattern = self.vid_pattern_edit.text()

        self.settings_changed.emit()
