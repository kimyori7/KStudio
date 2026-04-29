"""EditTab — 스크린샷·외부 파일 공통 편집 탭 (구 ScreenshotTab 의 일반화)."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QImage, QUndoStack
from PySide6.QtWidgets import QVBoxLayout, QWidget

from image_editor.canvas import LayerCanvas
from image_editor.format import read_kstudio
from image_editor.layer_model import LayerStack
from image_editor.layers.annotation_layer import AnnotationLayer
from image_editor.layers.image_layer import ImageLayer
from image_editor.selection import SelectionModel


class EditTab(QWidget):
    save_state_changed = Signal()

    def __init__(self, stack: LayerStack, *, source_label: str = "region") -> None:
        super().__init__()
        self.stack = stack
        self._source_label = source_label
        self._saved_path: Path | None = None

        self.canvas = LayerCanvas(stack)
        self.selection = SelectionModel(self)
        self.canvas.attach_selection(self.selection)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        self._last_needs_save = self.needs_save()
        self.undo_stack.cleanChanged.connect(self._check_needs_save_changed)

    # --- 팩토리 ---
    @classmethod
    def from_screenshot(cls, image: QImage, source_label: str) -> "EditTab":
        size = image.size()
        stack = LayerStack(size)
        stack.add_layer(ImageLayer(id=stack.next_id(), name="사진", pixmap=image))
        stack.add_layer(AnnotationLayer(id=stack.next_id(), name="레이어", canvas_size=size))
        return cls(stack, source_label=source_label)

    @classmethod
    def from_blank(cls, size: QSize, *, fill_white: bool = True,
                   source_label: str = "new") -> "EditTab":
        """빈 캔버스를 만든다 — 새로 만들기 다이얼로그용."""
        if size.width() <= 0 or size.height() <= 0:
            raise ValueError(f"잘못된 캔버스 크기: {size.width()}×{size.height()}")
        bg = QImage(size, QImage.Format_ARGB32)
        bg.fill(Qt.white if fill_white else Qt.transparent)
        stack = LayerStack(size)
        stack.add_layer(ImageLayer(id=stack.next_id(), name="배경", pixmap=bg))
        stack.add_layer(AnnotationLayer(id=stack.next_id(), name="레이어", canvas_size=size))
        return cls(stack, source_label=source_label)

    @classmethod
    def from_file(cls, path: Path) -> "EditTab":
        path = Path(path)
        if path.suffix.lower() == ".kstudio":
            stack = read_kstudio(path)
            tab = cls(stack, source_label="opened")
            tab._saved_path = path
            tab.undo_stack.setClean()
            return tab
        # 일반 raster: PNG / JPG / WebP / BMP
        img = QImage(str(path))
        if img.isNull():
            raise ValueError(f"이미지를 열 수 없음: {path}")
        size = img.size()
        stack = LayerStack(size)
        stack.add_layer(ImageLayer(id=stack.next_id(), name=path.name, pixmap=img))
        stack.add_layer(AnnotationLayer(id=stack.next_id(), name="레이어", canvas_size=size))
        return cls(stack, source_label="opened")

    # --- 외부 API (구 ScreenshotTab 호환) ---
    def image(self) -> QImage:
        return self.canvas.composite()

    def source_label(self) -> str:
        return self._source_label

    def is_saved(self) -> bool:
        return self._saved_path is not None

    def saved_path(self) -> Path | None:
        return self._saved_path

    def needs_save(self) -> bool:
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
