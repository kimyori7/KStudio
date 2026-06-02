"""AddLayerCommand — 레이어 한 개를 undo 가능하게 스택에 추가 (붙여넣기 등)."""
from __future__ import annotations
from typing import Optional

from PySide6.QtGui import QUndoCommand

from ..layer_model import LayerStack


class AddLayerCommand(QUndoCommand):
    """redo=레이어 추가 + 활성화, undo=제거 + 이전 활성 레이어 복원.

    RasterPaintCommand 와 달리 push 전에 미리 적용하지 않는다 — QUndoStack.push 가
    곧바로 redo() 를 호출하므로 추가 시점이 곧 첫 redo 다.
    """

    def __init__(
        self,
        stack: LayerStack,
        layer,
        *,
        above: Optional[int] = None,
        text: str = "붙여넣기",
    ) -> None:
        super().__init__(text)
        self._stack = stack
        self._layer = layer
        self._above = above
        self._prev_active = stack.active_layer_id

    def redo(self) -> None:
        self._stack.add_layer(self._layer, above=self._above)
        self._stack.set_active_layer(self._layer.id)

    def undo(self) -> None:
        self._stack.remove_layer(self._layer.id)
        if (
            self._prev_active is not None
            and self._stack.get_layer(self._prev_active) is not None
        ):
            self._stack.set_active_layer(self._prev_active)
