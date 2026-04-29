"""편집 툴바 — 옵션바 전용 (색·두께·undo·줌)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QColorDialog, QHBoxLayout, QLabel, QPushButton, QSlider,
    QSpinBox, QStackedWidget, QToolBar, QWidget,
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
    # 컨텍스트 도구 옵션 — 선택된 도구가 magic_wand / mask_brush 일 때만 보임.
    tolerance_changed = Signal(int)       # 마술봉 색 허용 범위
    brush_size_changed = Signal(int)      # 마스크 브러시 크기
    brush_mode_changed = Signal(str)      # "erase" 또는 "add"
    raster_size_changed = Signal(int)     # 래스터 브러시/지우개 크기

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

        # 컨텍스트 옵션 (마술봉 / 마스크 브러시 활성 시에만 보임)
        self.addSeparator()
        self._build_context_options()

    # --- API ---
    def preset_colors(self) -> tuple[str, ...]:
        return PRESET_COLORS

    def current_color(self) -> QColor:
        return QColor(self._current_color)

    def set_current_color(self, color: QColor) -> None:
        # 색이 같아도 버튼 체크 상태 동기화는 매번 수행 (앱 재시작 시 테두리 미표시 버그 방지).
        same = QColor(color) == self._current_color
        self._current_color = QColor(color)
        target_hex = self._current_color.name().lower()
        for i, btn in enumerate(self._color_buttons):
            btn.setChecked(PRESET_COLORS[i].lower() == target_hex)
        if not same:
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

    # --- 컨텍스트 옵션 (마술봉 / 마스크 브러시 / 래스터 브러시) ---
    def set_active_tool(self, tool_id: str) -> None:
        """현재 도구에 맞춰 컨텍스트 옵션 가시성 갱신."""
        if tool_id == "magic_wand":
            self._context_stack.setCurrentWidget(self._magic_wand_panel)
            self._context_action.setVisible(True)
        elif tool_id == "mask_brush":
            self._context_stack.setCurrentWidget(self._mask_brush_panel)
            self._context_action.setVisible(True)
        elif tool_id in ("brush", "eraser"):
            self._context_stack.setCurrentWidget(self._raster_brush_panel)
            self._context_action.setVisible(True)
        else:
            self._context_action.setVisible(False)
        # px 기반 도구는 단계별 두께 셀렉터 대신 px 슬라이더를 사용하므로 두께 컨트롤
        # 자체를 비활성화 — 사용자에게 어떤 컨트롤이 적용되는지 명확히 한다.
        px_tool = tool_id in ("brush", "eraser", "mask_brush")
        self._thickness_container.setEnabled(not px_tool)
        # 시각적 약화 — disabled 상태가 더 잘 보이도록 흐리게.
        self._thickness_container.setStyleSheet(
            "" if not px_tool else "QWidget { color: #555; } QPushButton { color: #555; }"
        )

    def set_tolerance(self, value: int) -> None:
        self._tolerance_slider.blockSignals(True)
        self._tolerance_slider.setValue(value)
        self._tolerance_label.setText(f"정도: {value}")
        self._tolerance_slider.blockSignals(False)

    def set_brush_size(self, value: int) -> None:
        self._brush_size_slider.blockSignals(True)
        self._brush_size_spin.blockSignals(True)
        self._brush_size_slider.setValue(value)
        self._brush_size_spin.setValue(value)
        self._brush_size_slider.blockSignals(False)
        self._brush_size_spin.blockSignals(False)

    def set_brush_mode(self, mode: str) -> None:
        if mode == "add":
            self._brush_add_btn.setChecked(True)
        else:
            self._brush_erase_btn.setChecked(True)

    def _build_context_options(self) -> None:
        self._context_stack = QStackedWidget(self)
        self._context_stack.setFixedHeight(28)

        # 마술봉 패널: tolerance 슬라이더
        self._magic_wand_panel = QWidget()
        mw_layout = QHBoxLayout(self._magic_wand_panel)
        mw_layout.setContentsMargins(4, 0, 4, 0)
        mw_layout.setSpacing(6)
        self._tolerance_label = QLabel("정도: 32")
        self._tolerance_label.setStyleSheet("color: #c8c8c8;")
        self._tolerance_label.setFixedWidth(64)
        self._tolerance_slider = QSlider(Qt.Horizontal)
        self._tolerance_slider.setRange(1, 128)
        self._tolerance_slider.setValue(32)
        self._tolerance_slider.setFixedWidth(160)
        self._tolerance_slider.setToolTip(
            "마술봉 색 허용 범위 — 값이 클수록 더 많은 색을 같은 영역으로 봄"
        )
        self._tolerance_slider.valueChanged.connect(self._on_tolerance_slider_changed)
        mw_layout.addWidget(self._tolerance_label)
        mw_layout.addWidget(self._tolerance_slider)
        mw_layout.addStretch(1)

        # 마스크 브러시 패널: 크기 + 모드 토글
        self._mask_brush_panel = QWidget()
        mb_layout = QHBoxLayout(self._mask_brush_panel)
        mb_layout.setContentsMargins(4, 0, 4, 0)
        mb_layout.setSpacing(6)
        mb_layout.addWidget(QLabel("크기:"))
        self._brush_size_slider = QSlider(Qt.Horizontal)
        self._brush_size_slider.setRange(1, 200)
        self._brush_size_slider.setValue(30)
        self._brush_size_slider.setFixedWidth(140)
        self._brush_size_slider.setToolTip("브러시 크기 (px) — 슬라이더 또는 우측 입력")
        self._brush_size_slider.valueChanged.connect(self._on_brush_size_slider_changed)
        # 우측 직접 입력 스핀박스 (슬라이더와 양방향 동기화)
        self._brush_size_spin = QSpinBox()
        self._brush_size_spin.setRange(1, 200)
        self._brush_size_spin.setValue(30)
        self._brush_size_spin.setSuffix("px")
        self._brush_size_spin.setFixedWidth(72)
        self._brush_size_spin.setToolTip("크기 직접 입력 (1~200 px)")
        self._brush_size_spin.valueChanged.connect(self._on_brush_size_spin_changed)
        mb_layout.addWidget(self._brush_size_slider)
        mb_layout.addWidget(self._brush_size_spin)

        # 모드 토글: 지우기 / 되살리기
        self._brush_mode_group = QButtonGroup(self)
        self._brush_mode_group.setExclusive(True)
        mode_qss = (
            "QPushButton { background: #2c2c2c; border: 1px solid #555; padding: 2px 8px; }"
            "QPushButton:hover { background: #3a3a3a; border: 1px solid #888; }"
            "QPushButton:checked { background: #1976d2; border: 2px solid #fff; }"
        )
        self._brush_erase_btn = QPushButton("🚫 지우기")
        self._brush_erase_btn.setCheckable(True)
        self._brush_erase_btn.setChecked(True)
        self._brush_erase_btn.setStyleSheet(mode_qss)
        self._brush_erase_btn.setToolTip("칠한 영역을 투명하게 (배경 제거)")
        self._brush_add_btn = QPushButton("✏ 되살리기")
        self._brush_add_btn.setCheckable(True)
        self._brush_add_btn.setStyleSheet(mode_qss)
        self._brush_add_btn.setToolTip("자동 누끼/마술봉이 잘못 지운 영역을 다시 보이게")
        self._brush_mode_group.addButton(self._brush_erase_btn)
        self._brush_mode_group.addButton(self._brush_add_btn)
        self._brush_erase_btn.toggled.connect(self._on_brush_mode_toggled)
        self._brush_add_btn.toggled.connect(self._on_brush_mode_toggled)
        mb_layout.addWidget(self._brush_erase_btn)
        mb_layout.addWidget(self._brush_add_btn)
        mb_layout.addStretch(1)

        # 래스터 브러시 / 지우개 패널: 사이즈 (슬라이더 + 직접 입력)
        self._raster_brush_panel = QWidget()
        rb_layout = QHBoxLayout(self._raster_brush_panel)
        rb_layout.setContentsMargins(4, 0, 4, 0)
        rb_layout.setSpacing(6)
        rb_layout.addWidget(QLabel("크기:"))
        self._raster_size_slider = QSlider(Qt.Horizontal)
        self._raster_size_slider.setRange(1, 200)
        self._raster_size_slider.setValue(20)
        self._raster_size_slider.setFixedWidth(140)
        self._raster_size_slider.setToolTip("브러시/지우개 크기 (px) — 슬라이더 또는 우측 입력")
        self._raster_size_slider.valueChanged.connect(self._on_raster_size_slider_changed)
        self._raster_size_spin = QSpinBox()
        self._raster_size_spin.setRange(1, 200)
        self._raster_size_spin.setValue(20)
        self._raster_size_spin.setSuffix("px")
        self._raster_size_spin.setFixedWidth(72)
        self._raster_size_spin.setToolTip("크기 직접 입력 (1~200 px)")
        self._raster_size_spin.valueChanged.connect(self._on_raster_size_spin_changed)
        rb_layout.addWidget(self._raster_size_slider)
        rb_layout.addWidget(self._raster_size_spin)
        rb_layout.addStretch(1)

        self._context_stack.addWidget(self._magic_wand_panel)
        self._context_stack.addWidget(self._mask_brush_panel)
        self._context_stack.addWidget(self._raster_brush_panel)
        self._context_action = self.addWidget(self._context_stack)
        self._context_action.setVisible(False)

    def _on_tolerance_slider_changed(self, value: int) -> None:
        self._tolerance_label.setText(f"정도: {value}")
        self.tolerance_changed.emit(value)

    def _on_brush_size_slider_changed(self, value: int) -> None:
        self._brush_size_spin.blockSignals(True)
        self._brush_size_spin.setValue(value)
        self._brush_size_spin.blockSignals(False)
        self.brush_size_changed.emit(value)

    def _on_brush_size_spin_changed(self, value: int) -> None:
        self._brush_size_slider.blockSignals(True)
        self._brush_size_slider.setValue(value)
        self._brush_size_slider.blockSignals(False)
        self.brush_size_changed.emit(value)

    def _on_brush_mode_toggled(self, _checked: bool) -> None:
        # toggled 가 두 버튼에서 두 번 발화되므로 erase 가 체크됐는지로만 판단
        mode = "erase" if self._brush_erase_btn.isChecked() else "add"
        self.brush_mode_changed.emit(mode)

    def _on_raster_size_slider_changed(self, value: int) -> None:
        self._raster_size_spin.blockSignals(True)
        self._raster_size_spin.setValue(value)
        self._raster_size_spin.blockSignals(False)
        self.raster_size_changed.emit(value)

    def _on_raster_size_spin_changed(self, value: int) -> None:
        self._raster_size_slider.blockSignals(True)
        self._raster_size_slider.setValue(value)
        self._raster_size_slider.blockSignals(False)
        self.raster_size_changed.emit(value)

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
        # 컨테이너 참조를 보관해 px 기반 도구(브러시/지우개/마스크 브러시) 선택 시
        # 비활성화한다 — 그 도구들은 두께 단계 대신 px 슬라이더를 쓰므로 어떤 컨트롤이
        # 적용되는지 사용자가 헷갈리지 않도록 함.
        self._thickness_container = container
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
