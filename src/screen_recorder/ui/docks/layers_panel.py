"""우측 도크 — 레이어 패널 (목록·👁·이름·불투명도·+/−/↑↓·우클릭)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget,
)


class _LayerListWidget(QListWidget):
    """Del/Backspace 누르면 활성 레이어 삭제."""

    def __init__(self, panel: "LayersPanel") -> None:
        super().__init__()
        self._panel = panel

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._panel.remove_active_layer()
            e.accept()
            return
        super().keyPressEvent(e)


class _LayerRow(QWidget):
    """한 레이어의 행 위젯 — 좌측 눈 아이콘(클릭 토글) + 이름 라벨.

    행 높이/폰트 크기는 QListWidget 의 기본 stylesheet 가 너무 빡빡해 텍스트가 위·아래로
    잘려 보이는 것을 방지하기 위해 명시적으로 지정한다.
    """

    visibility_toggled = Signal(int)   # layer_id

    ROW_HEIGHT = 30
    NORMAL_COLOR = "#E6E8EB"   # 기본 텍스트 — 어두운 패널 위에서 잘 읽히도록 거의 흰색
    HIDDEN_COLOR = "#6B6F77"   # 숨김 상태일 때 흐린 회색

    def __init__(self, layer_id: int, name: str, visible: bool) -> None:
        super().__init__()
        self._layer_id = layer_id
        self.setMinimumHeight(self.ROW_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 6, 4)
        layout.setSpacing(8)

        self._eye = QToolButton()
        self._eye.setAutoRaise(True)
        self._eye.setFixedSize(22, 22)
        self._eye.setCursor(Qt.PointingHandCursor)
        self._eye.setStyleSheet(
            "QToolButton { padding: 0; border: none; background: transparent;"
            " font-size: 14px; }"
        )
        self._eye.clicked.connect(lambda: self.visibility_toggled.emit(self._layer_id))
        layout.addWidget(self._eye)

        self._label = QLabel(name)
        self._label.setTextInteractionFlags(Qt.NoTextInteraction)
        layout.addWidget(self._label, stretch=1)
        # _label 이 만들어진 뒤에야 set_visible_icon 호출 가능 (라벨 스타일을 같이 갱신).
        self.set_visible_icon(visible)

    def set_visible_icon(self, visible: bool) -> None:
        # 눈 / 닫힌 눈 (보이기 / 숨기기) — 작은 아이콘 폰트 글자로 표현.
        self._eye.setText("👁" if visible else "🚫")
        self._eye.setToolTip("보이기 끄기" if visible else "보이기 켜기")
        # 라벨 색상을 명시적으로 지정 — QListWidget item 색상이 상속되지 않아
        # 기본 검정으로 떨어지면 어두운 배경에서 안 보이는 문제 방지.
        color = self.HIDDEN_COLOR if not visible else self.NORMAL_COLOR
        self._label.setStyleSheet(f"color: {color};")

    def set_label(self, name: str) -> None:
        self._label.setText(name)


from image_editor.layer_model import LayerStack
from image_editor.layers.annotation_layer import AnnotationLayer
from image_editor.layers.image_layer import ImageLayer


class LayersPanel(QWidget):
    def __init__(self, stack: LayerStack) -> None:
        super().__init__()
        self._stack = stack
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        title = QLabel("📚 레이어")
        title.setStyleSheet("color: #A0A4AB; font-weight: bold; padding: 2px 4px;")
        root.addWidget(title)

        self._list = _LayerListWidget(self)
        self._list.setSelectionMode(QListWidget.SingleSelection)
        # 활성 레이어 시인성: 진한 강조색 + 좌측 인디케이터. item 자체엔 padding 을
        # 주지 않는다 — 행 위젯(_LayerRow) 이 자체 contentsMargin/spacing 을 가지므로
        # 두 군데서 합쳐지면 텍스트가 잘려 보임.
        self._list.setStyleSheet("""
            QListWidget { background-color: #1A1C20; border: 1px solid #3C414B; border-radius: 6px; }
            QListWidget::item { padding: 0; border-left: 3px solid transparent; color: #CFD3DA; }
            QListWidget::item:hover { background-color: #2A2E36; }
            QListWidget::item:selected { background-color: #2E5D8A;
                                         border-left: 3px solid #4FC3F7; }
        """)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        # 드래그 앤 드롭으로 레이어 순서 바꾸기
        self._list.setDragEnabled(True)
        self._list.setAcceptDrops(True)
        self._list.setDragDropMode(QListWidget.InternalMove)
        self._list.setDefaultDropAction(Qt.MoveAction)
        # rowsMoved 시그널은 model 의 것을 사용
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        self._reordering = False
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
        layer = AnnotationLayer(id=new_id, name="레이어", canvas_size=self._stack.canvas_size)
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
        # drag-drop reorder 가 트리거한 모델 갱신 도중엔 list 를 다시 그리면 무한 루프.
        if self._reordering:
            return
        self._list.blockSignals(True)
        self._list.clear()
        for layer in reversed(self._stack.layers):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, layer.id)
            row = _LayerRow(layer.id, layer.name, bool(layer.visible))
            row.visibility_toggled.connect(self._on_visibility_button)
            # 명시적 행 높이 — 기본 sizeHint 가 너무 작아 글자가 잘려 보이는 문제 방지.
            item.setSizeHint(QSize(row.sizeHint().width(), _LayerRow.ROW_HEIGHT))
            self._list.addItem(item)
            self._list.setItemWidget(item, row)
        self._sync_selection(self._stack.active_layer_id if self._stack.active_layer_id is not None else -1)
        self._list.blockSignals(False)
        # 불투명도 슬라이더
        active = self._stack.active_layer()
        if active is not None:
            self._opacity.blockSignals(True)
            self._opacity.setValue(int(active.opacity * 100))
            self._opacity.blockSignals(False)

    def _on_visibility_button(self, layer_id: int) -> None:
        """행의 👁 버튼 클릭 — 해당 레이어 visible 토글 (활성 레이어 변경하지 않음)."""
        layer = self._stack.get_layer(layer_id)
        if layer is None:
            return
        layer.visible = not layer.visible
        self._stack.notify_layer_changed()

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

    def _on_rows_moved(self, *_args) -> None:
        """드래그-드롭으로 list 행 순서가 바뀐 직후 호출 — 새 순서를 LayerStack 으로 동기화.

        list 위쪽 = 가장 위 레이어 = stack 의 마지막 인덱스. 즉 list 와 stack 은 역순.
        """
        new_ids_top_first: list[int] = []
        for i in range(self._list.count()):
            it = self._list.item(i)
            lid = it.data(Qt.UserRole)
            if lid is not None:
                new_ids_top_first.append(int(lid))
        # stack 인덱스: 0=맨 아래, len-1=맨 위. list 와 역순.
        new_ids_bottom_first = list(reversed(new_ids_top_first))
        self._reordering = True
        try:
            for target_idx, lid in enumerate(new_ids_bottom_first):
                self._stack.move_layer(lid, target_idx)
        finally:
            self._reordering = False
        # 마지막에 한 번 갱신
        self._refresh()

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
