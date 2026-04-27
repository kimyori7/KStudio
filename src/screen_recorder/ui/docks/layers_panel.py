"""우측 도크 — 레이어 패널 (목록·👁·이름·불투명도·+/−/↑↓·우클릭)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem, QMenu, QPushButton,
    QSlider, QVBoxLayout, QWidget,
)

from image_editor.layer_model import LayerStack
from image_editor.layers.annotation_layer import AnnotationLayer
from image_editor.layers.image_layer import ImageLayer


class LayersPanel(QWidget):
    def __init__(self, stack: LayerStack) -> None:
        super().__init__()
        self._stack = stack
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        root.addWidget(self._list)

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QPushButton("불투명도", enabled=False))  # 라벨용
        self._opacity = QSlider(Qt.Horizontal)
        self._opacity.setRange(0, 100)
        self._opacity.setValue(100)
        self._opacity.valueChanged.connect(self._on_opacity_changed)
        opacity_row.addWidget(self._opacity)
        root.addLayout(opacity_row)

        btns = QHBoxLayout()
        self._btn_add = QPushButton("+")
        self._btn_remove = QPushButton("−")
        self._btn_up = QPushButton("↑")
        self._btn_down = QPushButton("↓")
        self._btn_add.clicked.connect(self.add_annotation_layer)
        self._btn_remove.clicked.connect(self.remove_active_layer)
        self._btn_up.clicked.connect(self.move_active_up)
        self._btn_down.clicked.connect(self.move_active_down)
        for b in (self._btn_add, self._btn_remove, self._btn_up, self._btn_down):
            btns.addWidget(b)
        root.addLayout(btns)

        self._stack.layers_changed.connect(self._refresh)
        self._stack.active_layer_changed.connect(self._sync_selection)
        self._list.currentRowChanged.connect(self._on_row_changed)

        self._refresh()

    # --- 외부 API (테스트) ---
    def layer_names_top_first(self) -> list[str]:
        return [self._row_to_layer(i).name for i in range(self._list.count())]

    def select_row(self, row: int) -> None:
        self._list.setCurrentRow(row)

    def toggle_visibility(self, row: int) -> None:
        layer = self._row_to_layer(row)
        if layer is None: return
        layer.visible = not layer.visible
        self._stack.notify_layer_changed()

    def rename_row(self, row: int, new_name: str) -> None:
        layer = self._row_to_layer(row)
        if layer is None or not new_name: return
        layer.name = new_name
        self._stack.notify_layer_changed()

    def add_annotation_layer(self) -> None:
        new_id = self._stack.next_id()
        layer = AnnotationLayer(id=new_id, name="주석", canvas_size=self._stack.canvas_size)
        self._stack.add_layer(layer, above=self._stack.active_layer_id)
        self._stack.set_active_layer(new_id)

    def remove_active_layer(self) -> None:
        if len(self._stack.layers) <= 1:
            return
        if self._stack.active_layer_id is None:
            return
        self._stack.remove_layer(self._stack.active_layer_id)

    def move_active_up(self) -> None:
        lid = self._stack.active_layer_id
        if lid is None: return
        idx = next((i for i, l in enumerate(self._stack.layers) if l.id == lid), None)
        if idx is None or idx == len(self._stack.layers) - 1: return
        self._stack.move_layer(lid, idx + 1)

    def move_active_down(self) -> None:
        lid = self._stack.active_layer_id
        if lid is None: return
        idx = next((i for i, l in enumerate(self._stack.layers) if l.id == lid), None)
        if idx is None or idx == 0: return
        self._stack.move_layer(lid, idx - 1)

    # --- 내부 ---
    def _row_to_layer(self, row: int):
        if row < 0 or row >= self._list.count(): return None
        lid = self._list.item(row).data(Qt.UserRole)
        return self._stack.get_layer(lid)

    def _refresh(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for layer in reversed(self._stack.layers):
            label = ("● " if layer.visible else "○ ") + layer.name
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, layer.id)
            self._list.addItem(item)
        self._sync_selection(self._stack.active_layer_id if self._stack.active_layer_id is not None else -1)
        self._list.blockSignals(False)
        # 불투명도 슬라이더
        active = self._stack.active_layer()
        if active is not None:
            self._opacity.blockSignals(True)
            self._opacity.setValue(int(active.opacity * 100))
            self._opacity.blockSignals(False)

    def _sync_selection(self, layer_id: int) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.UserRole) == layer_id:
                self._list.setCurrentRow(i)
                return
        self._list.setCurrentRow(-1)

    def _on_row_changed(self, row: int) -> None:
        if row < 0: return
        lid = self._list.item(row).data(Qt.UserRole)
        if lid != self._stack.active_layer_id:
            self._stack.set_active_layer(lid)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        layer = self._row_to_layer(row)
        if layer is None: return
        new_name, ok = QInputDialog.getText(self, "이름 변경", "새 이름:", text=layer.name)
        if ok:
            self.rename_row(row, new_name)

    def _on_opacity_changed(self, value: int) -> None:
        active = self._stack.active_layer()
        if active is None: return
        active.opacity = value / 100.0
        self._stack.notify_layer_changed()

    def _show_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None: return
        row = self._list.row(item)
        layer = self._row_to_layer(row)
        if layer is None: return
        menu = QMenu(self)
        act_visible = QAction("👁 보이기 토글", self)
        act_visible.triggered.connect(lambda: self.toggle_visibility(row))
        menu.addAction(act_visible)
        act_rename = QAction("이름 변경...", self)
        act_rename.triggered.connect(lambda: self._on_double_click(item))
        menu.addAction(act_rename)
        menu.addSeparator()
        act_up = QAction("위로", self); act_up.triggered.connect(self.move_active_up); menu.addAction(act_up)
        act_down = QAction("아래로", self); act_down.triggered.connect(self.move_active_down); menu.addAction(act_down)
        menu.addSeparator()
        if isinstance(layer, ImageLayer) and layer.mask is not None:
            act_clear_mask = QAction("배경 제거 해제", self)
            act_clear_mask.triggered.connect(lambda: self._clear_mask(layer))
            menu.addAction(act_clear_mask)
        menu.addSeparator()
        act_remove = QAction("삭제", self); act_remove.triggered.connect(self.remove_active_layer); menu.addAction(act_remove)
        menu.exec(self._list.mapToGlobal(pos))

    def _clear_mask(self, layer: ImageLayer) -> None:
        layer.mask = None
        self._stack.layers_changed.emit()
