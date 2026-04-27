"""편집 툴바 — 옵션바 전용 (색·두께·undo·줌)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QColorDialog, QHBoxLayout, QLabel, QPushButton, QSpinBox, QToolBar, QWidget,
)

from image_editor.thickness import THICKNESS_STEPS, DEFAULT_THICKNESS_STEP

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


class AnnotationToolbar(QToolBar):
    color_changed = Signal(QColor)
    thickness_changed = Signal(int)
    undo_requested = Signal()
    redo_requested = Signal()
    original_requested = Signal()  # 1.0 배율로 복귀
    zoom_input_changed = Signal(int)  # 사용자가 줌 입력값 변경 (단위: %)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("편집", parent)
        self.setMovable(False)

        self._current_color = QColor(PRESET_COLORS[0])
        self._current_thickness = DEFAULT_THICKNESS_STEP

        self._build_palette()
        self.addSeparator()
        self._build_thickness()
        self.addSeparator()
        # Undo/Redo — 18pt 큰 아이콘
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
        # 원본 + 줌 입력
        self._act_original = self._add_button(
            "원본", self._on_original, "원본 크기로 (Ctrl+0)"
        )
        self._zoom_spin = QSpinBox()
        self._zoom_spin.setRange(25, 400)
        self._zoom_spin.setValue(100)
        self._zoom_spin.setSuffix("%")
        self._zoom_spin.setSingleStep(10)
        self._zoom_spin.setFixedWidth(72)
        self._zoom_spin.setToolTip(
            "줌 배율 — 직접 숫자 입력 또는 ▲▼/휠로 조절. Ctrl+마우스휠로 캔버스 위에서도 가능"
        )
        self._zoom_spin.valueChanged.connect(self._on_zoom_spin_changed)
        self.addWidget(self._zoom_spin)

    # --- API ---
    def preset_colors(self) -> tuple[str, ...]:
        return PRESET_COLORS

    def current_color(self) -> QColor:
        return QColor(self._current_color)

    def set_current_color(self, color: QColor) -> None:
        if QColor(color) == self._current_color:
            return
        self._current_color = QColor(color)
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
        """현재 줌 배율을 spinbox 에 반영 (1.0 → 100). 시그널 차단으로 루프 방지."""
        percent = int(round(factor * 100))
        percent = max(25, min(400, percent))
        self._zoom_spin.blockSignals(True)
        self._zoom_spin.setValue(percent)
        self._zoom_spin.blockSignals(False)

    def _on_zoom_spin_changed(self, percent: int) -> None:
        self.zoom_input_changed.emit(percent)

    # --- internal build ---
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
            btn.setStyleSheet(
                f"QPushButton {{ background: {hexcolor}; border: 1px solid #555; }}"
                f"QPushButton:hover {{ border: 2px solid #fff; }}"
                f"QPushButton:checked {{ border: 3px solid #fff; }}"
            )
            btn.clicked.connect(lambda _, c=hexcolor: self.set_current_color(QColor(c)))
            layout.addWidget(btn)
            self._color_buttons.append(btn)
        self._color_buttons[0].setChecked(True)

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
            p.setPen(QPen(QColor("#888"), 1))
            p.setBrush(QColor("#cfcfcf"))
            p.drawRoundedRect(1, 2, size - 2, size - 4, 4, 4)
            spots = [
                (5, 6, "#E53935"),
                (12, 6, "#FDD835"),
                (5, 12, "#1E88E5"),
                (12, 12, "#43A047"),
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
        label = QLabel("두께:")
        label.setStyleSheet("color: #aaa; padding: 0 4px 0 0;")
        layout.addWidget(label)

        from image_editor.thickness import thickness_to_pixels
        self._thickness_buttons: dict[int, QPushButton] = {}
        thickness_qss = (
            "QPushButton { background: #2c2c2c; border: 1px solid #555; }"
            "QPushButton:hover { background: #3a3a3a; border: 1px solid #888; }"
            "QPushButton:checked {"
            "  background: #1976d2;"
            "  border: 2px solid #fff;"
            "}"
        )
        for step in THICKNESS_STEPS:
            btn = QPushButton()
            btn.setIcon(self._make_thickness_icon(step))
            btn.setIconSize(QSize(24, 14))
            btn.setFixedSize(32, 22)
            btn.setCheckable(True)
            btn.setToolTip(f"두께 {step}단계 ({thickness_to_pixels(step)}px) — 사각형/화살표 선 굵기")
            btn.setStyleSheet(thickness_qss)
            if step == DEFAULT_THICKNESS_STEP:
                btn.setChecked(True)
            btn.clicked.connect(lambda _, s=step: self.set_current_thickness_step(s))
            layout.addWidget(btn)
            self._thickness_buttons[step] = btn
        self.addWidget(container)

    def _make_thickness_icon(self, step: int) -> QIcon:
        """가운데 가로선이 단계별로 굵어지는 작은 아이콘."""
        visual_map = {1: 1, 2: 3, 3: 5, 4: 7}
        line_w = visual_map.get(step, 2)
        size_w, size_h = 24, 14
        pm = QPixmap(size_w, size_h)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(QColor("#e0e0e0"), line_w, Qt.SolidLine, Qt.RoundCap))
            y = size_h // 2
            margin = 3
            p.drawLine(margin, y, size_w - margin, y)
        finally:
            p.end()
        return QIcon(pm)

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
