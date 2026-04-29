"""MaskPaintCommand — MaskBrushTool 의 한 번의 스트로크를 undo-able 하게 감싸는 커맨드.

Tool 이 이미 layer.mask 에 in-place 로 칠한 상태에서 push 되므로 redo() 의 첫 호출은
no-op 처럼 보이지만 (이미 적용됨), 명시적으로 layer.mask = new_mask 로 동기화한다.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtGui import QImage, QUndoCommand

from ..layer_model import LayerStack
from ..layers.image_layer import ImageLayer


def _img_or_none(img: Optional[QImage]) -> Optional[QImage]:
    if img is None or img.isNull():
        return None
    return img


class MaskPaintCommand(QUndoCommand):
    def __init__(
        self,
        stack: LayerStack,
        layer_id: int,
        prev_mask: Optional[QImage],
        new_mask: Optional[QImage],
    ) -> None:
        super().__init__("마스크 브러시")
        self._stack = stack
        self._layer_id = layer_id
        self._prev_mask = _img_or_none(prev_mask)
        self._new_mask = _img_or_none(new_mask)
        self._first_redo = True

    def redo(self) -> None:
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer):
            return
        # 첫 redo 는 push 시점 — Tool 이 이미 layer.mask 를 new_mask 와 동일하게
        # 만들어둔 상태이므로 상태 변화 없음. 중복 시그널 emit 만 피한다.
        if self._first_redo:
            self._first_redo = False
            return
        layer.mask = self._new_mask
        self._stack.layers_changed.emit()

    def undo(self) -> None:
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer):
            return
        layer.mask = self._prev_mask
        self._stack.layers_changed.emit()
