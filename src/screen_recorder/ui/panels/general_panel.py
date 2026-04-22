"""일반 설정 패널."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QPushButton, QHBoxLayout,
    QRadioButton, QButtonGroup, QFileDialog,
)

from ...core.settings import GeneralSettings


class GeneralPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: GeneralSettings):
        super().__init__()
        self.settings = settings

        form = QFormLayout(self)

        dir_row = QWidget()
        dir_layout = QHBoxLayout(dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        self.dir_edit = QLineEdit(settings.output_dir)
        browse = QPushButton("📁")
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

        self.dir_edit.editingFinished.connect(self._sync)
        self.pattern_edit.editingFinished.connect(self._sync)
        self.video_radio.toggled.connect(self._sync)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "출력 폴더", self.dir_edit.text())
        if path:
            self.dir_edit.setText(path)
            self._sync()

    def _sync(self) -> None:
        self.settings.output_dir = self.dir_edit.text()
        self.settings.filename_pattern = self.pattern_edit.text()
        self.settings.mode = "gif" if self.gif_radio.isChecked() else "video"
        self.settings_changed.emit()
