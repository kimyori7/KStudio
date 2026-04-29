"""RasterPaintCommand — RasterBrushTool 의 한 스트로크를 undo-able 하게 감싸는 커맨드."""
from __future__ import annotations
from typing import Optional

from PySide6.QtGui import QImage, QUndoCommand

from ..layer_model import LayerStack
from ..layers.image_layer import ImageLayer


def _img_or_none(img: Optional[QImage]) -> Optional[QImage]:
    if img is None or img.isNull():
        return None
    return img


class RasterPaintCommand(QUndoCommand):
    def __init__(
        self,
        stack: LayerStack,
        layer_id: int,
        prev_pixmap: Optional[QImage],
        new_pixmap: Optional[QImage],
        text: str = "브러시",
    ) -> None:
        super().__init__(text)
        self._stack = stack
        self._layer_id = layer_id
        self._prev = _img_or_none(prev_pixmap)
        self._new = _img_or_none(new_pixmap)
        self._first_redo = True

    def redo(self) -> None:
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer):
            return
        # 첫 redo 는 push 시점 — Tool 이 이미 적용했으므로 no-op.
        if self._first_redo:
            self._first_redo = False
            return
        if self._new is not None:
            layer.pixmap = self._new.copy()
            self._stack.layers_changed.emit()

    def undo(self) -> None:
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer):
            return
        if self._prev is not None:
            layer.pixmap = self._prev.copy()
            self._stack.layers_changed.emit()
