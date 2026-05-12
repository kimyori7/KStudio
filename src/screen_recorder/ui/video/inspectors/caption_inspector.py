"""CaptionInspector — 캡션 효과 편집 폼.

값이 바뀔 때마다 새 CaptionEffect 를 만들어 effect_changed 로 발화한다.
인스펙터는 _emitting 가드로 setX 중에는 시그널을 무시 (load 시 무한 루프 방지).
"""
from __future__ import annotations
from dataclasses import replace
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QDoubleSpinBox, QFontComboBox,
    QFormLayout, QGridLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton,
    QSlider, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from ....core.i18n import tr
from ....effects.types.caption import (
    CaptionEffect, Font, Stroke, Background, Position, Fade,
)
from .base import InspectorBase


_ANCHORS_3x3 = [
    ["top-left", "top-center", "top-right"],
    ["middle-left", "middle-center", "middle-right"],
    ["bottom-left", "bottom-center", "bottom-right"],
]


class CaptionInspector(InspectorBase):
    """캡션 효과 편집 폼."""

    def __init__(self) -> None:
        super().__init__()
        self._emitting_guard: bool = False
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self._layout.addLayout(form)

        # ---- 텍스트 ----
        self.text_edit = QTextEdit()
        self.text_edit.setFixedHeight(60)
        self.text_edit.textChanged.connect(self._on_any_change)
        form.addRow(tr("텍스트"), self.text_edit)

        # ---- 폰트 + 크기 + 굵기 ----
        font_row = QHBoxLayout()
        self.font_family = QFontComboBox()
        self.font_family.currentFontChanged.connect(self._on_any_change)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 120)
        self.font_size.setValue(36)
        self.font_size.valueChanged.connect(self._on_any_change)
        self.bold_check = QCheckBox(tr("굵게"))
        self.bold_check.toggled.connect(self._on_any_change)
        font_row.addWidget(self.font_family, stretch=1)
        font_row.addWidget(self.font_size)
        font_row.addWidget(self.bold_check)
        form.addRow(tr("폰트"), font_row)

        # ---- 글자 색 ----
        self._fill_color: str = "#ffffff"
        self.fill_btn = QPushButton()
        self._refresh_color_button(self.fill_btn, self._fill_color)
        self.fill_btn.clicked.connect(self._pick_fill_color)
        form.addRow(tr("글자 색"), self.fill_btn)

        # ---- 외곽선 ----
        stroke_row = QHBoxLayout()
        self.stroke_check = QCheckBox(tr("외곽선"))
        self.stroke_check.toggled.connect(self._on_any_change)
        self._stroke_color: str = "#000000"
        self.stroke_color_btn = QPushButton()
        self._refresh_color_button(self.stroke_color_btn, self._stroke_color)
        self.stroke_color_btn.clicked.connect(self._pick_stroke_color)
        self.stroke_width = QSpinBox()
        self.stroke_width.setRange(0, 6)
        self.stroke_width.setValue(2)
        self.stroke_width.valueChanged.connect(self._on_any_change)
        stroke_row.addWidget(self.stroke_check)
        stroke_row.addWidget(self.stroke_color_btn)
        stroke_row.addWidget(QLabel(tr("두께")))
        stroke_row.addWidget(self.stroke_width)
        form.addRow("", stroke_row)

        # ---- 그림자 ----
        self.shadow_check = QCheckBox(tr("그림자"))
        self.shadow_check.toggled.connect(self._on_any_change)
        form.addRow("", self.shadow_check)

        # ---- 텍스트 정렬 (multi-line 내부 정렬, anchor 와 직교) ----
        self.align_group = QButtonGroup(self)
        align_row = QHBoxLayout()
        self.align_left_btn = QRadioButton(tr("← 좌"))
        self.align_center_btn = QRadioButton(tr("≡ 중앙"))
        self.align_right_btn = QRadioButton(tr("우 →"))
        self.align_center_btn.setChecked(True)
        for btn in (self.align_left_btn, self.align_center_btn, self.align_right_btn):
            self.align_group.addButton(btn)
            btn.toggled.connect(lambda on, b=btn: on and self._on_any_change())
            align_row.addWidget(btn)
        align_row.addStretch(1)
        form.addRow(tr("텍스트 정렬"), align_row)

        # ---- 배경 박스 ----
        bg_row = QHBoxLayout()
        self.bg_check = QCheckBox(tr("배경"))
        self.bg_check.toggled.connect(self._on_any_change)
        self._bg_color: str = "#000000"
        self.bg_color_btn = QPushButton()
        self._refresh_color_button(self.bg_color_btn, self._bg_color)
        self.bg_color_btn.clicked.connect(self._pick_bg_color)
        self.bg_opacity = QSlider(Qt.Horizontal)
        self.bg_opacity.setRange(0, 100)
        self.bg_opacity.setValue(50)
        self.bg_opacity.valueChanged.connect(self._on_any_change)
        bg_row.addWidget(self.bg_check)
        bg_row.addWidget(self.bg_color_btn)
        bg_row.addWidget(QLabel(tr("불투명도")))
        bg_row.addWidget(self.bg_opacity, stretch=1)
        form.addRow("", bg_row)

        # ---- 위치 9-zone + 자유 위치 ----
        self.anchor_group = QButtonGroup(self)
        self.anchor_buttons: dict[str, QRadioButton] = {}
        anchor_grid = QGridLayout()
        for r, row in enumerate(_ANCHORS_3x3):
            for c, anchor in enumerate(row):
                rb = QRadioButton()
                rb.setToolTip(anchor)
                rb.toggled.connect(lambda on, a=anchor: on and self._on_anchor_change())
                self.anchor_group.addButton(rb)
                self.anchor_buttons[anchor] = rb
                anchor_grid.addWidget(rb, r, c)
        form.addRow(tr("위치"), anchor_grid)

        # 자유 위치 라디오 + 정규화 좌표 입력. free 모드일 때 9-zone 라디오는 모두 unchecked.
        free_row = QHBoxLayout()
        self.free_anchor_radio = QRadioButton(tr("자유 위치"))
        self.free_anchor_radio.setToolTip(tr("미리보기에서 캡션을 드래그하거나 아래 좌표 입력"))
        self.free_anchor_radio.toggled.connect(
            lambda on: on and self._on_anchor_change(free=True)
        )
        self.anchor_group.addButton(self.free_anchor_radio)
        self.anchor_buttons["free"] = self.free_anchor_radio
        free_row.addWidget(self.free_anchor_radio)
        free_row.addWidget(QLabel(tr("X")))
        self.free_x_spin = QDoubleSpinBox()
        self.free_x_spin.setRange(0.0, 1.0)
        self.free_x_spin.setSingleStep(0.05)
        self.free_x_spin.setDecimals(2)
        self.free_x_spin.setValue(0.5)
        self.free_x_spin.valueChanged.connect(self._on_any_change)
        free_row.addWidget(self.free_x_spin)
        free_row.addWidget(QLabel(tr("Y")))
        self.free_y_spin = QDoubleSpinBox()
        self.free_y_spin.setRange(0.0, 1.0)
        self.free_y_spin.setSingleStep(0.05)
        self.free_y_spin.setDecimals(2)
        self.free_y_spin.setValue(0.5)
        self.free_y_spin.valueChanged.connect(self._on_any_change)
        free_row.addWidget(self.free_y_spin)
        form.addRow("", free_row)
        # 9-zone 선택 시 free 좌표 입력은 비활성화 (시각적 신호).
        self._update_free_spinbox_enabled(False)

        # ---- 페이드 ----
        fade_row = QHBoxLayout()
        self.fade_in_spin = QSpinBox()
        self.fade_in_spin.setRange(0, 5000)
        self.fade_in_spin.setValue(300)
        self.fade_in_spin.setSuffix(" ms")
        self.fade_in_spin.valueChanged.connect(self._on_any_change)
        self.fade_out_spin = QSpinBox()
        self.fade_out_spin.setRange(0, 5000)
        self.fade_out_spin.setValue(300)
        self.fade_out_spin.setSuffix(" ms")
        self.fade_out_spin.valueChanged.connect(self._on_any_change)
        fade_row.addWidget(QLabel(tr("페이드 인")))
        fade_row.addWidget(self.fade_in_spin)
        fade_row.addWidget(QLabel(tr("페이드 아웃")))
        fade_row.addWidget(self.fade_out_spin)
        form.addRow("", fade_row)

        self._layout.addStretch(1)
        # 초기 상태는 disabled (set_effect(None) 와 같은 효과)
        self._set_form_enabled(False)

    # ---------- public ----------
    def set_effect(self, effect: Optional[CaptionEffect]) -> None:
        super().set_effect(effect)
        if effect is None:
            self._set_form_enabled(False)
            return
        self._emitting_guard = True
        try:
            # text_edit 의 현재 내용과 동일하면 setPlainText 호출 자체를 생략.
            # setPlainText 는 커서를 위치 0 으로 리셋하는데, 사용자가 타이핑 중에
            # sidecar_replaced → refresh_from_sidecar → set_effect 경로가 매 IME
            # 이벤트마다 들어오면 다음 입력 글자가 위치 0 에 끼어들어가 "확대" →
            # "대확" 식으로 순서가 뒤집힌다. 같은 텍스트는 갱신 불필요.
            if self.text_edit.toPlainText() != effect.text:
                self.text_edit.setPlainText(effect.text)
            self.font_family.setCurrentText(effect.font.family)
            self.font_size.setValue(effect.font.size)
            self.bold_check.setChecked(effect.font.bold)
            self._fill_color = effect.fill
            self._refresh_color_button(self.fill_btn, self._fill_color)
            self.stroke_check.setChecked(effect.stroke is not None)
            if effect.stroke is not None:
                self._stroke_color = effect.stroke.color
                self._refresh_color_button(self.stroke_color_btn, self._stroke_color)
                self.stroke_width.setValue(effect.stroke.width)
            self.shadow_check.setChecked(effect.shadow)
            self.bg_check.setChecked(effect.background is not None)
            if effect.background is not None:
                self._bg_color = effect.background.color
                self._refresh_color_button(self.bg_color_btn, self._bg_color)
                self.bg_opacity.setValue(int(effect.background.opacity * 100))
            rb = self.anchor_buttons.get(effect.position.anchor)
            if rb is not None:
                rb.setChecked(True)
            is_free = (effect.position.anchor == "free")
            self._update_free_spinbox_enabled(is_free)
            if is_free:
                self.free_x_spin.setValue(effect.position.offset_x)
                self.free_y_spin.setValue(effect.position.offset_y)
            self.fade_in_spin.setValue(effect.fade.in_ms)
            self.fade_out_spin.setValue(effect.fade.out_ms)
            align = getattr(effect, "text_align", "center")
            if align == "left":
                self.align_left_btn.setChecked(True)
            elif align == "right":
                self.align_right_btn.setChecked(True)
            else:
                self.align_center_btn.setChecked(True)
        finally:
            self._emitting_guard = False
        self._set_form_enabled(True)

    # ---------- internal ----------
    def _set_form_enabled(self, enabled: bool) -> None:
        for w in (self.text_edit, self.font_family, self.font_size, self.bold_check,
                  self.fill_btn, self.stroke_check, self.stroke_color_btn,
                  self.stroke_width, self.shadow_check, self.bg_check,
                  self.bg_color_btn, self.bg_opacity, self.fade_in_spin,
                  self.fade_out_spin):
            w.setEnabled(enabled)
        for rb in self.anchor_buttons.values():
            rb.setEnabled(enabled)
        if not enabled:
            self.free_x_spin.setEnabled(False)
            self.free_y_spin.setEnabled(False)

    def _update_free_spinbox_enabled(self, free: bool) -> None:
        """free anchor 일 때만 X/Y spinbox 활성화 (시각적 신호)."""
        self.free_x_spin.setEnabled(free)
        self.free_y_spin.setEnabled(free)

    def _on_anchor_change(self, *, free: bool = False) -> None:
        """라디오 변경 핸들러. free 토글 시 spinbox 활성화 갱신 + 9-zone → free 전환 시
        offset 을 정규화 좌표(0~1)로 초기화 (둘은 의미가 다른 단위)."""
        if self._emitting_guard or self._effect is None:
            return
        if free:
            self._update_free_spinbox_enabled(True)
            # 9-zone 의 픽셀 offset → free 의 정규화 의미로 자동 변환은 어렵다.
            # 사용자가 free 로 처음 전환하면 화면 정중앙으로 초기화. 이후 미세 조정.
            self._emitting_guard = True
            try:
                self.free_x_spin.setValue(0.5)
                self.free_y_spin.setValue(0.5)
            finally:
                self._emitting_guard = False
        else:
            self._update_free_spinbox_enabled(False)
        self._on_any_change()

    def _refresh_color_button(self, btn: QPushButton, color_hex: str) -> None:
        btn.setText(color_hex)
        btn.setStyleSheet(f"background-color: {color_hex}; color: "
                          + ("#000" if QColor(color_hex).lightness() > 128 else "#fff"))

    def _pick_fill_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._fill_color), self, tr("글자 색"))
        if c.isValid():
            self._fill_color = c.name()
            self._refresh_color_button(self.fill_btn, self._fill_color)
            self._on_any_change()

    def _pick_stroke_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._stroke_color), self, tr("외곽선 색"))
        if c.isValid():
            self._stroke_color = c.name()
            self._refresh_color_button(self.stroke_color_btn, self._stroke_color)
            self._on_any_change()

    def _pick_bg_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._bg_color), self, tr("배경 색"))
        if c.isValid():
            self._bg_color = c.name()
            self._refresh_color_button(self.bg_color_btn, self._bg_color)
            self._on_any_change()

    def _on_any_change(self) -> None:
        if self._emitting_guard or self._effect is None:
            return
        # 현재 폼 → 새 CaptionEffect (id 보존)
        anchor = "bottom-center"
        for a, rb in self.anchor_buttons.items():
            if rb.isChecked():
                anchor = a
                break
        # free 일 때만 spinbox 값을 사용. 9-zone 모드는 기존 offset(픽셀 단위 미세 조정) 유지.
        if anchor == "free":
            offset_x = self.free_x_spin.value()
            offset_y = self.free_y_spin.value()
        else:
            offset_x = self._effect.position.offset_x
            offset_y = self._effect.position.offset_y
        if self.align_left_btn.isChecked():
            text_align = "left"
        elif self.align_right_btn.isChecked():
            text_align = "right"
        else:
            text_align = "center"
        new_eff = replace(
            self._effect,
            text=self.text_edit.toPlainText(),
            font=Font(family=self.font_family.currentFont().family(),
                      size=self.font_size.value(),
                      bold=self.bold_check.isChecked()),
            fill=self._fill_color,
            stroke=(Stroke(color=self._stroke_color, width=self.stroke_width.value())
                    if self.stroke_check.isChecked() else None),
            shadow=self.shadow_check.isChecked(),
            background=(Background(color=self._bg_color,
                                   opacity=self.bg_opacity.value() / 100.0)
                        if self.bg_check.isChecked() else None),
            position=Position(anchor=anchor,
                              offset_x=offset_x,
                              offset_y=offset_y),
            fade=Fade(in_ms=self.fade_in_spin.value(),
                      out_ms=self.fade_out_spin.value()),
            text_align=text_align,
        )
        self._effect = new_eff
        self.effect_changed.emit(new_eff)
