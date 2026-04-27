"""우측 도크 — 레이어 패널 (기본 목록 + 활성 레이어 클릭)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from image_editor.layer_model import LayerStack


class LayersPanel(QWidget):
    def __init__(self, stack: LayerStack) -> None:
        super().__init__()
        self._stack = stack
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        layout.addWidget(self._list)

        self._stack.layers_changed.connect(self._refresh)
        self._stack.active_layer_changed.connect(self._sync_selection)
        self._list.currentRowChanged.connect(self._on_row_changed)

        self._refresh()

    # --- 외부 ---
    def layer_names_top_first(self) -> list[str]:
        return [self._list.item(i).text() for i in range(self._list.count())]

    def select_row(self, row: int) -> None:
        self._list.setCurrentRow(row)

    # --- 내부 ---
    def _refresh(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        # 위 = 화면에서도 위 = LayerStack 인덱스 큰 쪽
        for layer in reversed(self._stack.layers):
            item = QListWidgetItem(layer.name)
            item.setData(Qt.UserRole, layer.id)
            self._list.addItem(item)
        self._sync_selection(self._stack.active_layer_id if self._stack.active_layer_id is not None else -1)
        self._list.blockSignals(False)

    def _sync_selection(self, layer_id: int) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.UserRole) == layer_id:
                self._list.setCurrentRow(i)
                return
        self._list.setCurrentRow(-1)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self._list.item(row)
        lid = item.data(Qt.UserRole)
        if lid != self._stack.active_layer_id:
            self._stack.set_active_layer(lid)
