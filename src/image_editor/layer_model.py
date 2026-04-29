"""LayerStack — 레이어 목록 + 시그널 (UI 무관 순수 모델)."""
from __future__ import annotations
from itertools import count
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import QObject, QSize, Signal

if TYPE_CHECKING:
    from .layers.base import Layer


class LayerStack(QObject):
    layers_changed = Signal()                 # 추가/삭제/순서/표시·숨김/속성 변경
    layer_pixmap_changed = Signal(int)        # 단일 레이어 픽스맵만 갱신 (브러시 등 핫패스용)
    canvas_size_changed = Signal()
    active_layer_changed = Signal(int)        # active_layer_id (None 이면 -1)

    def __init__(self, canvas_size: QSize) -> None:
        super().__init__()
        self._canvas_size = QSize(canvas_size)
        self._layers: list["Layer"] = []
        self._active_id: Optional[int] = None
        self._id_seq = count(1)

    # --- 조회 ---
    @property
    def canvas_size(self) -> QSize:
        return QSize(self._canvas_size)

    @property
    def layers(self) -> list:
        return list(self._layers)

    @property
    def active_layer_id(self) -> Optional[int]:
        return self._active_id

    def get_layer(self, layer_id: int):
        for l in self._layers:
            if l.id == layer_id:
                return l
        return None

    def active_layer(self):
        if self._active_id is None:
            return None
        return self.get_layer(self._active_id)

    def next_id(self) -> int:
        """새 레이어를 만들 때 사용할 ID 발급 (테스트의 _DummyLayer 처럼 외부에서 ID 를 정해 넣어도 무방)."""
        return next(self._id_seq)

    # --- 변경 ---
    def add_layer(self, layer, *, above: Optional[int] = None) -> None:
        if above is None:
            self._layers.append(layer)
        else:
            for i, l in enumerate(self._layers):
                if l.id == above:
                    self._layers.insert(i + 1, layer)
                    break
            else:
                self._layers.append(layer)
        if self._active_id is None:
            self._active_id = layer.id
            self.active_layer_changed.emit(layer.id)
        self.layers_changed.emit()

    def remove_layer(self, layer_id: int) -> None:
        for i, l in enumerate(self._layers):
            if l.id == layer_id:
                del self._layers[i]
                break
        else:
            return
        if self._active_id == layer_id:
            self._active_id = self._layers[-1].id if self._layers else None
            self.active_layer_changed.emit(self._active_id if self._active_id is not None else -1)
        self.layers_changed.emit()

    def move_layer(self, layer_id: int, new_index: int) -> None:
        for i, l in enumerate(self._layers):
            if l.id == layer_id:
                layer = self._layers.pop(i)
                self._layers.insert(max(0, min(new_index, len(self._layers))), layer)
                self.layers_changed.emit()
                return

    def set_active_layer(self, layer_id: Optional[int]) -> None:
        if layer_id is not None and self.get_layer(layer_id) is None:
            return
        self._active_id = layer_id
        self.active_layer_changed.emit(layer_id if layer_id is not None else -1)

    def set_canvas_size(self, size: QSize) -> None:
        if size == self._canvas_size:
            return
        self._canvas_size = QSize(size)
        self.canvas_size_changed.emit()

    def notify_layer_changed(self) -> None:
        """레이어 속성(visible/opacity/이름/내부 상태) 이 외부에서 바뀌었을 때 호출."""
        self.layers_changed.emit()

    def notify_pixmap_changed(self, layer_id: int) -> None:
        """단일 레이어의 픽스맵만 바뀐 핫패스 (브러시/지우개 등) — 전체 rebuild 회피."""
        self.layer_pixmap_changed.emit(layer_id)
