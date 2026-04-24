"""스크린샷 한 장을 보여주는 탭 위젯 + 저장 상태 보관."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QScrollArea, QLabel, QWidget, QVBoxLayout


class ScreenshotTab(QWidget):
    save_state_changed = Signal()  # is_saved() 값이 바뀌면 발행

    def __init__(self, image: QImage, source_label: str = "region"):
        super().__init__()
        self._image = image
        self._source_label = source_label
        self._saved_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignCenter)

        self._label = QLabel()
        self._label.setPixmap(QPixmap.fromImage(image))
        self._label.setAlignment(Qt.AlignCenter)
        self._scroll.setWidget(self._label)

        layout.addWidget(self._scroll)

    # ---------- 외부 API ----------

    def image(self) -> QImage:
        return self._image

    def source_label(self) -> str:
        return self._source_label

    def is_saved(self) -> bool:
        return self._saved_path is not None

    def saved_path(self) -> Path | None:
        return self._saved_path

    def mark_saved(self, path: Path) -> None:
        was_saved = self.is_saved()
        self._saved_path = path
        if not was_saved:
            self.save_state_changed.emit()
