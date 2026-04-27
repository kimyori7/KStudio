"""편집 툴바 — 도구 선택 / 팔레트 / 두께 / Undo / 뷰 버튼."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QColorDialog, QHBoxLayout, QLabel, QPushButton, QToolBar, QWidget,
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
    original_requested = Signal()  # 1.0 배율로 복귀

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
        # Undo/Redo — 18pt + 명시 큰 크기
        self._act_undo = self._add_button("⟲", self._on_undo, "실행취소 (Ctrl+Z)")
        self._act_redo = self._add_button("⟳", self._on_redo, "다시실행 (Ctrl+Y)")
        for act in (self._act_undo, self._act_redo):
            btn = self.widgetForAction(act)
            if btn is not None:
                f = btn.font()
                f.setPointSize(18)
                f.setBold(True)
                btn.setFont(f)
                btn.setMinimumSize(40, 32)
        self.addSeparator()
        # 원본 크기로 가는 버튼 + 현재 줌 배율 라벨
        self._act_original = self._add_button(
            "원본", self._on_original, "원본 크기로 (Ctrl+0). Ctrl+마우스휠로 자유 줌"
        )
        self._zoom_label = QLabel("100%")
        self._zoom_label.setMinimumWidth(50)
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setStyleSheet(
            "QLabel { color: #ddd; padding: 0 8px; font-weight: bold; }"
        )
        self._zoom_label.setToolTip("현재 줌 배율 (Ctrl+마우스휠로 조절)")
        self.addWidget(self._zoom_label)

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

    def set_zoom_label(self, factor: float) -> None:
        """현재 줌 배율을 라벨에 표시 (1.0 → '100%')."""
        percent = int(round(factor * 100))
        self._zoom_label.setText(f"{percent}%")

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
            btn.setFixedSize(22, 22)
            btn.setCheckable(True)
            btn.setToolTip(f"{hexcolor}")
            # 선택 표시: 흰색 단일 테두리 3px (이전 검정 outline 제거 — 색이 가려져 어색).
            btn.setStyleSheet(
                f"QPushButton {{ background: {hexcolor}; border: 1px solid #555; }}"
                f"QPushButton:hover {{ border: 2px solid #fff; }}"
                f"QPushButton:checked {{ border: 3px solid #fff; }}"
            )
            btn.clicked.connect(lambda _, c=hexcolor: self.set_current_color(QColor(c)))
            layout.addWidget(btn)
            self._color_buttons.append(btn)
        self._color_buttons[0].setChecked(True)

        # 커스텀 색상 선택 — 직접 그린 팔레트 아이콘 (이모지는 Windows 폰트
        # 의존성으로 안정적이지 않음)
        custom = QPushButton()
        custom.setIcon(self._make_palette_icon())
        custom.setIconSize(custom.size())
        custom.setFixedSize(28, 22)
        custom.setToolTip("더 많은 색… (커스텀 색상 선택)")
        custom.clicked.connect(self._on_custom_color)
        layout.addWidget(custom)

        self.addWidget(container)

    def _make_palette_icon(self) -> QIcon:
        """팔레트 모양 작은 아이콘 — 둥근 사각 위에 4 색점."""
        size = 18
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            # 팔레트 본체 (회색 둥근 사각)
            p.setPen(QPen(QColor("#888"), 1))
            p.setBrush(QColor("#cfcfcf"))
            p.drawRoundedRect(1, 2, size - 2, size - 4, 4, 4)
            # 색점 4개 (빨/노/파/초)
            spots = [
                (5, 6, "#E53935"),   # 빨
                (12, 6, "#FDD835"),  # 노
                (5, 12, "#1E88E5"),  # 파
                (12, 12, "#43A047"), # 초
            ]
            p.setPen(Qt.NoPen)
            for cx, cy, c in spots:
                p.setBrush(QColor(c))
                p.drawEllipse(cx - 2, cy - 2, 4, 4)
        finally:
            p.end()
        return QIcon(pm)

    def _build_thickness(self) -> None:
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        from .annotation.thickness import thickness_to_pixels
        self._thickness_buttons: dict[int, QPushButton] = {}
        # 두께 버튼: 체크 시 강한 파란 배경으로 명확히 강조
        thickness_qss = (
            "QPushButton { background: #2c2c2c; color: #ddd; border: 1px solid #555; }"
            "QPushButton:hover { background: #3a3a3a; border: 1px solid #888; }"
            "QPushButton:checked {"
            "  background: #1976d2; color: white;"
            "  border: 2px solid #fff;"
            "  font-weight: bold;"
            "}"
        )
        for step in THICKNESS_STEPS:
            btn = QPushButton(str(step))
            btn.setFixedSize(26, 22)
            btn.setCheckable(True)
            btn.setToolTip(f"두께 {step}단계 ({thickness_to_pixels(step)}px)")
            btn.setStyleSheet(thickness_qss)
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

    def _on_original(self) -> None:
        self.original_requested.emit()
