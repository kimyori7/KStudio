"""EditTab — 스크린샷·외부 파일 공통 편집 탭 (구 ScreenshotTab 의 일반화)."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QUndoStack
from PySide6.QtWidgets import QVBoxLayout, QWidget

from image_editor.canvas import LayerCanvas
from image_editor.format import read_kstudio
from image_editor.layer_model import LayerStack
from image_editor.layers.annotation_layer import AnnotationLayer
from image_editor.layers.image_layer import ImageLayer
from image_editor.operations.raster_paint import RasterPaintCommand
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
        # 캔버스에서 Del 키가 눌리면 selection 영역만 삭제. WindowShortcut 으로
        # 등록하면 LayersPanel 의 Del(레이어 삭제)을 가로채므로 캔버스 keyPressEvent
        # 에서만 발화하도록 위임.
        self.canvas.delete_selection_requested.connect(self.delete_selection)

    # --- 팩토리 ---
    @staticmethod
    def _make_bg_layer(stack: LayerStack, size: QSize, *, fill_white: bool) -> ImageLayer:
        """배경 ImageLayer 생성 — 흰색 또는 투명. stack.add_layer 는 호출자 책임."""
        bg = QImage(size, QImage.Format_ARGB32)
        bg.fill(Qt.white if fill_white else Qt.transparent)
        return ImageLayer(id=stack.next_id(), name="배경", pixmap=bg)

    @classmethod
    def from_screenshot(cls, image: QImage, source_label: str) -> "EditTab":
        """캡처: 투명 배경 + 사진 두 레이어 (주석 레이어는 도구 사용 시점에 자동 생성).

        배경을 투명으로 두는 이유: 사용자가 누끼/지우개로 사진 픽셀을 지웠을 때 그
        영역이 "비어 있음" (PNG 알파)을 그대로 유지하도록. 흰 배경이 깔려 있으면
        지운 영역이 흰색으로 남아 PNG 투명을 의도한 사용자가 혼란.
        """
        size = image.size()
        stack = LayerStack(size)
        stack.add_layer(cls._make_bg_layer(stack, size, fill_white=False))
        photo = ImageLayer(id=stack.next_id(), name="사진", pixmap=image)
        stack.add_layer(photo)
        stack.set_active_layer(photo.id)
        return cls(stack, source_label=source_label)

    @classmethod
    def from_blank(cls, size: QSize, *, fill_white: bool = False,
                   source_label: str = "new") -> "EditTab":
        """빈 캔버스를 만든다 — 새로 만들기 다이얼로그용.

        fill_white=False(기본): 투명 배경. PNG 등 알파 보존 포맷으로 그대로 사용 가능.
        fill_white=True: 흰 배경. 종이 위에 그리는 느낌 / JPG 등 알파 미지원 포맷 의식.
        주석 레이어는 만들지 않음 — rect/arrow/text 도구 선택 시 MainWindow 가 자동으로
        하나 끼워 넣는다.
        """
        if size.width() <= 0 or size.height() <= 0:
            raise ValueError(f"잘못된 캔버스 크기: {size.width()}×{size.height()}")
        stack = LayerStack(size)
        stack.add_layer(cls._make_bg_layer(stack, size, fill_white=fill_white))
        return cls(stack, source_label=source_label)

    @classmethod
    def from_file(cls, path: Path) -> "EditTab":
        path = Path(path)
        if path.suffix.lower() == ".kstudio":
            stack = read_kstudio(path)
            tab = cls(stack, source_label="opened")
            tab._saved_path = path
            tab.undo_stack.setClean()
            tab._last_needs_save = tab.needs_save()
            return tab
        # 일반 raster: PNG / JPG / WebP / BMP — 투명 배경 + 사진 두 레이어.
        img = QImage(str(path))
        if img.isNull():
            raise ValueError(f"이미지를 열 수 없음: {path}")
        size = img.size()
        stack = LayerStack(size)
        stack.add_layer(cls._make_bg_layer(stack, size, fill_white=False))
        photo = ImageLayer(id=stack.next_id(), name=path.name, pixmap=img)
        stack.add_layer(photo)
        stack.set_active_layer(photo.id)
        tab = cls(stack, source_label="opened")
        # 디스크에서 막 로드한 파일은 "이미 저장된 상태" 다 — 저장 마커가 안 떠야 함.
        # (편집 안 한 상태로는 needs_save() == False.) Ctrl+S 시 같은 경로에 덮어쓰기.
        tab._saved_path = path
        tab.undo_stack.setClean()
        tab._last_needs_save = tab.needs_save()
        return tab

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

    # --- 영역 삭제 ---
    def delete_selection(self, *, command_text: str = "삭제") -> None:
        """selection 영역만 활성 ImageLayer 에서 투명으로 만든다 (undo 가능).

        selection 이 없거나 활성 레이어가 ImageLayer 가 아니면 no-op.
        Ctrl+X(잘라내기) 도 이 메서드를 사용하며 command_text 로 undo 라벨을 구분.
        """
        if not self.selection.has_selection():
            return
        rect = self.selection.rect()
        if rect is None:
            return
        layer = self.stack.active_layer()
        if not isinstance(layer, ImageLayer):
            return
        local_rect = QRect(rect)
        local_rect.translate(-int(layer.offset.x()), -int(layer.offset.y()))
        prev_pixmap = QImage(layer.pixmap).copy()
        new_pixmap = QImage(layer.pixmap).copy()
        painter = QPainter(new_pixmap)
        try:
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(local_rect, Qt.transparent)
        finally:
            painter.end()
        # RasterPaintCommand 는 첫 redo() 를 no-op 으로 둠 (브러시 툴은 push 전에 이미
        # 픽스맵을 바꿔 두므로). 우리도 같은 약속을 따라 push 전에 직접 적용한다.
        layer.pixmap = new_pixmap.copy()
        self.stack.notify_pixmap_changed(layer.id)
        cmd = RasterPaintCommand(self.stack, layer.id, prev_pixmap, new_pixmap, text=command_text)
        self.undo_stack.push(cmd)
        self.selection.clear()

    # --- 내부 ---
    def _check_needs_save_changed(self) -> None:
        now = self.needs_save()
        if now != self._last_needs_save:
            self._last_needs_save = now
            self.save_state_changed.emit()
