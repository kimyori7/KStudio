"""CropCommand — 캔버스 크기 변경 + 레이어 offset 일괄 갱신."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QUndoCommand

from ..layer_model import LayerStack


class CropCommand(QUndoCommand):
    def __init__(self, stack: LayerStack, rect: QRect) -> None:
        super().__init__("자르기")
        self._stack = stack
        self._rect = QRect(rect)
        self._prev_canvas_size: QSize = stack.canvas_size
        self._prev_offsets: dict[int, QPoint] = {}

    def redo(self) -> None:
        self._prev_offsets.clear()
        for l in self._stack.layers:
            if hasattr(l, "offset"):
                self._prev_offsets[l.id] = QPoint(l.offset)
            l.apply_crop(self._rect)
        self._stack.set_canvas_size(QSize(self._rect.width(), self._rect.height()))
        self._stack.layers_changed.emit()

    def undo(self) -> None:
        for l in self._stack.layers:
            if l.id in self._prev_offsets and hasattr(l, "offset"):
                l.offset = QPoint(self._prev_offsets[l.id])
            else:
                # AnnotationLayer 등: 역방향 평행이동
                inv = QRect(-self._rect.x(), -self._rect.y(),
                            self._prev_canvas_size.width(), self._prev_canvas_size.height())
                l.apply_crop(inv)
        self._stack.set_canvas_size(self._prev_canvas_size)
        self._stack.layers_changed.emit()
