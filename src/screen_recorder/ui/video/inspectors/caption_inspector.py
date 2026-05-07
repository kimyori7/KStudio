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
    QButtonGroup, QCheckBox, QColorDialog, QFontComboBox, QFormLayout,
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton, QSlider,
    QSpinBox, QTextEdit, QVBoxLayout, QWidget,
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

        # ---- 위치 9-zone ----
        self.anchor_group = QButtonGroup(self)
        self.anchor_buttons: dict[str, QRadioButton] = {}
        anchor_grid = QGridLayout()
        for r, row in enumerate(_ANCHORS_3x3):
            for c, anchor in enumerate(row):
                rb = QRadioButton()
                rb.setToolTip(anchor)
                rb.toggled.connect(lambda on, a=anchor: on and self._on_any_change())
                self.anchor_group.addButton(rb)
                self.anchor_buttons[anchor] = rb
                anchor_grid.addWidget(rb, r, c)
        form.addRow(tr("위치"), anchor_grid)

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
            self.fade_in_spin.setValue(effect.fade.in_ms)
            self.fade_out_spin.setValue(effect.fade.out_ms)
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
                              offset_x=self._effect.position.offset_x,
                              offset_y=self._effect.position.offset_y),
            fade=Fade(in_ms=self.fade_in_spin.value(),
                      out_ms=self.fade_out_spin.value()),
        )
        self._effect = new_eff
        self.effect_changed.emit(new_eff)
