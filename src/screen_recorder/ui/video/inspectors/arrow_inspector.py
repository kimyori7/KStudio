"""ArrowInspector — 화살표 효과 편집 폼.

SpeedInspector / ZoomInspector 와 동일 패턴 — _emitting_guard, dataclasses.replace,
effect_changed / effect_deleted 시그널.

스핀:
- start.x / start.y, end.x / end.y — 0~1 정규화 좌표
- thickness — 1~64 px (source 단위)
- fade_in / fade_out — 0~3000 ms
- in_ms / out_ms — 효과 시간 범위

버튼:
- 색상 선택 (QColorDialog)
- '이 화살표 삭제'
"""
from __future__ import annotations
from dataclasses import replace
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QWidget,
)

from ....effects.types.arrow import ArrowEffect, Point
from .base import InspectorBase


class ArrowInspector(InspectorBase):
    """화살표 효과 편집 폼."""

    effect_deleted = Signal(str)   # effect_id

    def __init__(self) -> None:
        super().__init__()
        self._emitting_guard: bool = False
        self._effect: Optional[ArrowEffect] = None
        self._color: str = "#ff4040"
        self._build_ui()
        self._set_form_enabled(False)

    def _build_ui(self) -> None:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self._layout.addLayout(form)

        # 색상 (가장 자주 만짐 — 맨 위)
        color_row = QHBoxLayout()
        self._color_swatch = QLabel("    ")
        self._color_swatch.setStyleSheet(f"background:{self._color}; border:1px solid #888;")
        self._color_swatch.setFixedSize(40, 22)
        self._color_btn = QPushButton("색상…")
        self._color_btn.clicked.connect(self._on_color_clicked)
        color_row.addWidget(self._color_swatch)
        color_row.addWidget(self._color_btn)
        color_row.addStretch(1)
        color_holder = QWidget()
        color_holder.setLayout(color_row)
        form.addRow("색", color_holder)

        self._thickness_spin = QSpinBox()
        self._thickness_spin.setRange(1, 64)
        self._thickness_spin.setSuffix(" px")
        self._thickness_spin.valueChanged.connect(self._on_any_change)
        form.addRow("굵기", self._thickness_spin)

        # 화살촉(머리) 크기 배율 — 굵기와 독립. 1.0 = 기본.
        self._head_scale_spin = QDoubleSpinBox()
        self._head_scale_spin.setRange(0.2, 5.0)
        self._head_scale_spin.setSingleStep(0.1)
        self._head_scale_spin.setDecimals(1)
        self._head_scale_spin.setValue(1.0)
        self._head_scale_spin.setSuffix(" ×")
        self._head_scale_spin.valueChanged.connect(self._on_any_change)
        form.addRow("머리 크기", self._head_scale_spin)

        self._fade_in_spin = QSpinBox()
        self._fade_in_spin.setRange(0, 3000)
        self._fade_in_spin.setSingleStep(50)
        self._fade_in_spin.setSuffix(" ms")
        self._fade_in_spin.valueChanged.connect(self._on_any_change)
        form.addRow("페이드 인", self._fade_in_spin)

        self._fade_out_spin = QSpinBox()
        self._fade_out_spin.setRange(0, 3000)
        self._fade_out_spin.setSingleStep(50)
        self._fade_out_spin.setSuffix(" ms")
        self._fade_out_spin.valueChanged.connect(self._on_any_change)
        form.addRow("페이드 아웃", self._fade_out_spin)

        self._in_spin = QSpinBox()
        self._in_spin.setRange(0, 9_999_999)
        self._in_spin.setSuffix(" ms")
        self._in_spin.valueChanged.connect(self._on_any_change)
        form.addRow("시작", self._in_spin)

        self._out_spin = QSpinBox()
        self._out_spin.setRange(0, 9_999_999)
        self._out_spin.setSuffix(" ms")
        self._out_spin.valueChanged.connect(self._on_any_change)
        form.addRow("끝", self._out_spin)

        # 좌표 (자주 안 만짐 — 미리보기에서 직접 드래그 가능, 맨 밑)
        self._start_x_spin = self._mk_norm_spin()
        form.addRow("시작 X (0~1)", self._start_x_spin)
        self._start_y_spin = self._mk_norm_spin()
        form.addRow("시작 Y (0~1)", self._start_y_spin)
        self._end_x_spin = self._mk_norm_spin()
        form.addRow("끝 X (0~1)", self._end_x_spin)
        self._end_y_spin = self._mk_norm_spin()
        form.addRow("끝 Y (0~1)", self._end_y_spin)

        self._delete_btn = QPushButton("이 화살표 삭제")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        form.addRow("", self._delete_btn)

        self._layout.addStretch(1)

    def _mk_norm_spin(self) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(0.0, 1.0)
        sp.setSingleStep(0.05)
        sp.setDecimals(2)
        sp.valueChanged.connect(self._on_any_change)
        return sp

    def set_effect(self, effect: Optional[ArrowEffect]) -> None:
        super().set_effect(effect)
        if effect is None:
            self._effect = None
            self._set_form_enabled(False)
            return
        if not isinstance(effect, ArrowEffect):
            return
        self._emitting_guard = True
        try:
            self._effect = effect
            self._start_x_spin.setValue(float(effect.start.x))
            self._start_y_spin.setValue(float(effect.start.y))
            self._end_x_spin.setValue(float(effect.end.x))
            self._end_y_spin.setValue(float(effect.end.y))
            self._color = str(effect.color)
            self._color_swatch.setStyleSheet(
                f"background:{self._color}; border:1px solid #888;")
            self._thickness_spin.setValue(int(effect.thickness))
            self._head_scale_spin.setValue(float(getattr(effect, "head_scale", 1.0)))
            self._fade_in_spin.setValue(int(effect.fade.in_ms))
            self._fade_out_spin.setValue(int(effect.fade.out_ms))
            self._in_spin.setValue(int(effect.in_ms))
            self._out_spin.setValue(int(effect.out_ms))
        finally:
            self._emitting_guard = False
        self._set_form_enabled(True)

    def load_effect(self, effect: Optional[ArrowEffect]) -> None:
        self.set_effect(effect)

    def _set_form_enabled(self, enabled: bool) -> None:
        for w in (self._start_x_spin, self._start_y_spin,
                  self._end_x_spin, self._end_y_spin,
                  self._color_btn, self._thickness_spin, self._head_scale_spin,
                  self._fade_in_spin, self._fade_out_spin,
                  self._in_spin, self._out_spin, self._delete_btn):
            w.setEnabled(enabled)

    def _on_color_clicked(self) -> None:
        if self._effect is None:
            return
        chosen = QColorDialog.getColor(QColor(self._color), self, "화살표 색")
        if not chosen.isValid():
            return
        self._color = chosen.name()
        self._color_swatch.setStyleSheet(
            f"background:{self._color}; border:1px solid #888;")
        self._on_any_change()

    def _on_any_change(self, *_) -> None:
        if self._emitting_guard or self._effect is None:
            return
        from ....effects.types.arrow import Fade
        in_ms = int(self._in_spin.value())
        out_ms = int(self._out_spin.value())
        if out_ms <= in_ms:
            out_ms = in_ms + 1
        try:
            new_eff = replace(
                self._effect,
                start=Point(x=float(self._start_x_spin.value()),
                            y=float(self._start_y_spin.value())),
                end=Point(x=float(self._end_x_spin.value()),
                          y=float(self._end_y_spin.value())),
                color=self._color,
                thickness=int(self._thickness_spin.value()),
                head_scale=float(self._head_scale_spin.value()),
                fade=Fade(in_ms=int(self._fade_in_spin.value()),
                          out_ms=int(self._fade_out_spin.value())),
                in_ms=in_ms,
                out_ms=out_ms,
            )
        except ValueError:
            return
        self._effect = new_eff
        self.effect_changed.emit(new_eff)

    def _on_delete_clicked(self) -> None:
        if self._effect is None:
            return
        self.effect_deleted.emit(self._effect.id)
