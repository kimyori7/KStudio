"""스크린샷 한 장 + 주석 편집 캔버스 + 저장 상태 보관."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QImage, QUndoStack
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .annotation.canvas import AnnotationCanvas


class ScreenshotTab(QWidget):
    save_state_changed = Signal()  # needs_save() 값이 바뀔 때마다 발행

    def __init__(self, image: QImage, source_label: str = "region"):
        super().__init__()
        self._source_label = source_label
        self._saved_path: Path | None = None

        self.canvas = AnnotationCanvas(image)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(0)  # 무제한

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        # needs_save 상태 추적
        self._last_needs_save = self.needs_save()
        self.undo_stack.cleanChanged.connect(self._check_needs_save_changed)

    # --- 외부 API ---
    def image(self) -> QImage:
        """주석이 합성된 현재 이미지 (저장/복사용)."""
        return self.canvas.render_composite()

    def source_label(self) -> str:
        return self._source_label

    def is_saved(self) -> bool:
        return self._saved_path is not None

    def saved_path(self) -> Path | None:
        return self._saved_path

    def needs_save(self) -> bool:
        """● 표시 조건: 저장된 적 없거나 + 저장 이후 변경됨."""
        return (not self.is_saved()) or (not self.undo_stack.isClean())

    def mark_saved(self, path: Path) -> None:
        self._saved_path = path
        self.undo_stack.setClean()
        self._check_needs_save_changed()

    # --- 내부 ---
    def _check_needs_save_changed(self) -> None:
        now = self.needs_save()
        if now != self._last_needs_save:
            self._last_needs_save = now
            self.save_state_changed.emit()
