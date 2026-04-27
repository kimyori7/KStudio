"""편집 툴바 — 도구 선택 / 팔레트 / 두께 / Undo / 뷰 버튼."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor
from PySide6.QtWidgets import (
    QColorDialog, QHBoxLayout, QPushButton, QToolBar, QWidget,
)

from .annotation.thickness import THICKNESS_STEPS, DEFAULT_THICKNESS_STEP

PRESET_COLORS: tuple[str, ...] = (
    "#E53935",  # 빨강 (기본)
    "#FB8C00",  # 주황
    "#FDD835",  # 노랑
    "#43A047",  # 초록
    "#1E88E5",  # 파랑
    "#8E24AA",  # 보라
    "#212121",  # 검정
    "#FAFAFA",  # 흰색
)

TOOL_IDS: tuple[str, ...] = ("select", "rect", "arrow", "text")
TOOL_LABELS: dict[str, str] = {
    "select": "선택",
    "rect": "사각형",
    "arrow": "화살표",
    "text": "텍스트",
}
TOOL_SHORTCUTS: dict[str, str] = {
    "select": "V", "rect": "R", "arrow": "A", "text": "T",
}


class AnnotationToolbar(QToolBar):
    tool_changed = Signal(str)
    color_changed = Signal(QColor)
    thickness_changed = Signal(int)
    undo_requested = Signal()
    redo_requested = Signal()
    fit_requested = Signal()
    hundred_percent_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("편집", parent)
        self.setMovable(False)

        self._current_tool = "select"
        self._current_color = QColor(PRESET_COLORS[0])
        self._current_thickness = DEFAULT_THICKNESS_STEP

        self._tool_actions: dict[str, QAction] = {}
        self._build_tool_group()
        self.addSeparator()
        self._build_palette()
        self.addSeparator()
        self._build_thickness()
        self.addSeparator()
        self._act_undo = self._add_button("↶", self._on_undo, "실행취소 (Ctrl+Z)")
        self._act_redo = self._add_button("↷", self._on_redo, "다시실행 (Ctrl+Y)")
        self.addSeparator()
        self._add_button("Fit", self._on_fit, "창에 맞춤 (Ctrl+0)")
        self._add_button("100%", self._on_hundred, "원본 크기 (Ctrl+1)")

    # --- API ---
    def tool_ids(self) -> tuple[str, ...]:
        return TOOL_IDS

    def current_tool_id(self) -> str:
        return self._current_tool

    def set_current_tool(self, tool_id: str) -> None:
        if tool_id not in TOOL_IDS or tool_id == self._current_tool:
            return
        self._current_tool = tool_id
        self._tool_actions[tool_id].setChecked(True)
        self.tool_changed.emit(tool_id)

    def preset_colors(self) -> tuple[str, ...]:
        return PRESET_COLORS

    def current_color(self) -> QColor:
        return QColor(self._current_color)

    def set_current_color(self, color: QColor) -> None:
        if QColor(color) == self._current_color:
            return
        self._current_color = QColor(color)
        # 프리셋 중 일치하는 것 체크 (없으면 모두 해제 — 커스텀 색)
        target_hex = self._current_color.name().lower()
        for i, btn in enumerate(self._color_buttons):
            btn.setChecked(PRESET_COLORS[i].lower() == target_hex)
        self.color_changed.emit(QColor(self._current_color))

    def current_thickness_step(self) -> int:
        return self._current_thickness

    def set_current_thickness_step(self, step: int) -> None:
        if step not in THICKNESS_STEPS or step == self._current_thickness:
            return
        self._current_thickness = step
        for s, btn in self._thickness_buttons.items():
            btn.setChecked(s == step)
        self.thickness_changed.emit(step)

    def set_undo_enabled(self, enabled: bool) -> None:
        self._act_undo.setEnabled(enabled)

    def set_redo_enabled(self, enabled: bool) -> None:
        self._act_redo.setEnabled(enabled)

    # --- internal build ---
    def _build_tool_group(self) -> None:
        group = QActionGroup(self)
        group.setExclusive(True)
        for tid in TOOL_IDS:
            label = TOOL_LABELS[tid]
            act = QAction(label, self)
            act.setCheckable(True)
            act.setShortcut(TOOL_SHORTCUTS[tid])
            act.setToolTip(f"{label} ({TOOL_SHORTCUTS[tid]})")
            if tid == "select":
                act.setChecked(True)
            act.triggered.connect(lambda _=False, t=tid: self.set_current_tool(t))
            group.addAction(act)
            self.addAction(act)
            self._tool_actions[tid] = act

    def _build_palette(self) -> None:
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._color_buttons: list[QPushButton] = []
        for hexcolor in PRESET_COLORS:
            btn = QPushButton()
            btn.setFixedSize(20, 20)
            btn.setCheckable(True)
            btn.setStyleSheet(
                f"QPushButton {{ background: {hexcolor}; border: 1px solid #555; }}"
                f"QPushButton:checked {{ border: 2px solid #000; }}"
            )
            btn.clicked.connect(lambda _, c=hexcolor: self.set_current_color(QColor(c)))
            layout.addWidget(btn)
            self._color_buttons.append(btn)
        self._color_buttons[0].setChecked(True)

        custom = QPushButton("…")
        custom.setFixedSize(24, 20)
        custom.setToolTip("더 많은 색…")
        custom.clicked.connect(self._on_custom_color)
        layout.addWidget(custom)

        self.addWidget(container)

    def _build_thickness(self) -> None:
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._thickness_buttons: dict[int, QPushButton] = {}
        for step in THICKNESS_STEPS:
            btn = QPushButton(str(step))
            btn.setFixedSize(24, 20)
            btn.setCheckable(True)
            if step == DEFAULT_THICKNESS_STEP:
                btn.setChecked(True)
            btn.clicked.connect(lambda _, s=step: self.set_current_thickness_step(s))
            layout.addWidget(btn)
            self._thickness_buttons[step] = btn
        self.addWidget(container)

    def _add_button(self, text: str, slot, tooltip: str) -> QAction:
        act = QAction(text, self)
        act.setToolTip(tooltip)
        act.triggered.connect(slot)
        self.addAction(act)
        return act

    # --- slots ---
    def _on_custom_color(self) -> None:
        color = QColorDialog.getColor(self._current_color, self, "색상 선택")
        if color.isValid():
            self.set_current_color(color)

    def _on_undo(self) -> None:
        self.undo_requested.emit()

    def _on_redo(self) -> None:
        self.redo_requested.emit()

    def _on_fit(self) -> None:
        self.fit_requested.emit()

    def _on_hundred(self) -> None:
        self.hundred_percent_requested.emit()
