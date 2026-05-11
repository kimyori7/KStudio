"""ZoomInspector — 줌 효과 편집 폼.

SpeedInspector 패턴 답습 — `_emitting_guard` 로 set_effect 중에는 시그널을
무시하고, 위젯 변경 시 dataclasses.replace 로 새 ZoomEffect 를 만들어
effect_changed 발화.

v1 정적 줌: 단일 (cx, cy, scale) 입력이 start 와 end 양쪽에 동시 반영된다.
키프레임 애니메이션 (start ≠ end) 은 v2 후속.

콤보:
- ease — '이즈 인/아웃' / '선형' / '이즈 인' / '이즈 아웃' ↔ 'in-out' / 'linear' / 'in' / 'out'

스핀:
- cx, cy: 0.0~1.0, step 0.05 — 영상 너비/높이의 정규화 좌표
- scale: 0.1~10.0, step 0.5 — 배율
- in_anim_ms / out_anim_ms: 0~3000 ms — 진입/이탈 애니메이션
- in_ms / out_ms: 효과 시간 범위

'이 줌 삭제' 버튼은 effect_deleted(effect_id) 시그널 발화.
"""
from __future__ import annotations
from dataclasses import replace
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QPushButton, QSpinBox,
)

from ....effects.types.zoom import ZoomEffect, ZoomPoint
from .base import InspectorBase


# ---- combo 매핑 ----
# ease 콤보 — 라벨 ↔ enum 값 양방향. 첫 항목이 ZoomEffect 의 기본값 'in-out'.
_EASE_LABELS: list[tuple[str, str]] = [
    ("이즈 인/아웃", "in-out"),
    ("선형",         "linear"),
    ("이즈 인",       "in"),
    ("이즈 아웃",     "out"),
]
_EASE_LABEL_TO_VALUE = {label: value for label, value in _EASE_LABELS}
_EASE_VALUE_TO_LABEL = {value: label for label, value in _EASE_LABELS}


class ZoomInspector(InspectorBase):
    """줌 효과 편집 폼 (v1 — 정적 줌)."""

    # InspectorBase 의 effect_changed 외에 effect_deleted 추가 (panel 이 bubble).
    effect_deleted = Signal(str)   # effect_id

    def __init__(self) -> None:
        super().__init__()
        self._emitting_guard: bool = False
        self._effect: Optional[ZoomEffect] = None
        self._build_ui()
        self._set_form_enabled(False)

    # ---------- UI build ----------
    def _build_ui(self) -> None:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self._layout.addLayout(form)

        # ---- cx ----
        self._cx_spin = QDoubleSpinBox()
        self._cx_spin.setRange(0.0, 1.0)
        self._cx_spin.setSingleStep(0.05)
        self._cx_spin.setDecimals(2)
        self._cx_spin.valueChanged.connect(self._on_any_change)
        form.addRow("중심 X (0~1)", self._cx_spin)

        # ---- cy ----
        self._cy_spin = QDoubleSpinBox()
        self._cy_spin.setRange(0.0, 1.0)
        self._cy_spin.setSingleStep(0.05)
        self._cy_spin.setDecimals(2)
        self._cy_spin.valueChanged.connect(self._on_any_change)
        form.addRow("중심 Y (0~1)", self._cy_spin)

        # ---- scale ----
        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(0.1, 10.0)
        self._scale_spin.setSingleStep(0.5)
        self._scale_spin.setDecimals(2)
        self._scale_spin.setSuffix("×")
        self._scale_spin.valueChanged.connect(self._on_any_change)
        form.addRow("배율", self._scale_spin)

        # ---- ease ----
        self._ease_combo = QComboBox()
        for label, _value in _EASE_LABELS:
            self._ease_combo.addItem(label)
        self._ease_combo.currentIndexChanged.connect(self._on_any_change)
        form.addRow("이징", self._ease_combo)

        # ---- in_anim / out_anim ms ----
        self._in_anim_spin = QSpinBox()
        self._in_anim_spin.setRange(0, 3000)
        self._in_anim_spin.setSingleStep(50)
        self._in_anim_spin.setSuffix(" ms")
        self._in_anim_spin.valueChanged.connect(self._on_any_change)
        form.addRow("진입 애니", self._in_anim_spin)

        self._out_anim_spin = QSpinBox()
        self._out_anim_spin.setRange(0, 3000)
        self._out_anim_spin.setSingleStep(50)
        self._out_anim_spin.setSuffix(" ms")
        self._out_anim_spin.valueChanged.connect(self._on_any_change)
        form.addRow("이탈 애니", self._out_anim_spin)

        # ---- in / out ms ----
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

        # ---- 미리보기 체크박스 ----
        # 체크 ON → 이 zoom 구간 재생 시 실제 화면이 줌인 (export 결과 동일).
        # OFF (기본) → 가이드 박스만 표시, 화면은 그대로.
        self._preview_chk = QCheckBox("이 줌 구간 재생 시 화면 줌인 적용")
        self._preview_chk.toggled.connect(self._on_any_change)
        form.addRow("미리보기", self._preview_chk)

        # ---- 삭제 버튼 ----
        self._delete_btn = QPushButton("이 줌 삭제")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        form.addRow("", self._delete_btn)

        self._layout.addStretch(1)

    # ---------- public API ----------
    def set_effect(self, effect: Optional[ZoomEffect]) -> None:
        """효과를 폼에 채워 넣음. None 이면 disable."""
        super().set_effect(effect)
        if effect is None:
            self._effect = None
            self._set_form_enabled(False)
            return
        if not isinstance(effect, ZoomEffect):
            return
        self._emitting_guard = True
        try:
            self._effect = effect
            # v1: start 만 표시 (start == end 가정).
            # cx/cy 의 valid range 는 scale 에 따라 [half, 1-half] — 가장자리 clamp.
            self._update_cx_cy_range(float(effect.start.scale))
            self._cx_spin.setValue(float(effect.start.cx))
            self._cy_spin.setValue(float(effect.start.cy))
            self._scale_spin.setValue(float(effect.start.scale))
            # ease 콤보
            label = _EASE_VALUE_TO_LABEL.get(effect.ease, _EASE_LABELS[0][0])
            self._ease_combo.setCurrentText(label)
            # in_anim / out_anim
            self._in_anim_spin.setValue(int(effect.in_anim_ms))
            self._out_anim_spin.setValue(int(effect.out_anim_ms))
            # in / out
            self._in_spin.setValue(int(effect.in_ms))
            self._out_spin.setValue(int(effect.out_ms))
            # 미리보기 체크박스
            self._preview_chk.setChecked(bool(effect.preview))
        finally:
            self._emitting_guard = False
        self._set_form_enabled(True)

    # 별칭 — 일부 호출자가 load_effect 라는 이름을 기대할 수 있어 alias 제공.
    def load_effect(self, effect: Optional[ZoomEffect]) -> None:
        self.set_effect(effect)

    # ---------- internal ----------
    def _set_form_enabled(self, enabled: bool) -> None:
        for w in (self._cx_spin, self._cy_spin, self._scale_spin,
                  self._ease_combo, self._in_anim_spin, self._out_anim_spin,
                  self._in_spin, self._out_spin, self._preview_chk, self._delete_btn):
            w.setEnabled(enabled)

    def _on_any_change(self, *_) -> None:
        if self._emitting_guard or self._effect is None:
            return
        scale = float(self._scale_spin.value())
        # scale 이 바뀌면 cx/cy 의 valid range 도 같이 바뀜 — 가장자리 over-shoot 방지.
        self._update_cx_cy_range(scale)
        cx = float(self._cx_spin.value())
        cy = float(self._cy_spin.value())
        # ease — 라벨 → enum 값
        ease_label = self._ease_combo.currentText()
        ease = _EASE_LABEL_TO_VALUE.get(ease_label, "in-out")
        in_anim_ms = int(self._in_anim_spin.value())
        out_anim_ms = int(self._out_anim_spin.value())
        # in/out — 음수/역전 방지. Effect.__post_init__ 은 strict out > in 요구.
        in_ms = int(self._in_spin.value())
        out_ms = int(self._out_spin.value())
        if out_ms <= in_ms:
            out_ms = in_ms + 1
        # v1: start == end (정적 줌). cx/cy/scale 변경이 양쪽에 동시 반영.
        try:
            new_pt = ZoomPoint(cx=cx, cy=cy, scale=scale)
            new_eff = replace(
                self._effect,
                start=new_pt,
                end=ZoomPoint(cx=cx, cy=cy, scale=scale),
                ease=ease,
                in_anim_ms=in_anim_ms,
                out_anim_ms=out_anim_ms,
                in_ms=in_ms,
                out_ms=out_ms,
                preview=bool(self._preview_chk.isChecked()),
            )
        except ValueError:
            # ZoomPoint / ZoomEffect __post_init__ 검증 실패 (범위 등) — 무시.
            return
        self._effect = new_eff
        self.effect_changed.emit(new_eff)

    def _on_delete_clicked(self) -> None:
        if self._effect is None:
            return
        self.effect_deleted.emit(self._effect.id)

    def _update_cx_cy_range(self, scale: float) -> None:
        """scale 에 따라 cx/cy 의 valid range 를 [half, 1-half] 로 동적 변경.

        줌 박스의 모서리가 frame 안에 머무는 조건 — half = 0.5 / scale. scale<=1 면
        박스가 frame 보다 크거나 같아 0.5 로 잠금 (effective no-op). 인스펙터에서 입력
        값을 자동으로 끝까지 못 가게 막아, 가장자리에서 "더 가는 느낌" 회귀 차단.
        드래그 경로는 _compute_drag_clamp 가 동일 로직으로 처리.
        """
        half = 0.5 / max(0.1, scale)
        prev_guard = self._emitting_guard
        self._emitting_guard = True
        try:
            if half >= 0.5:
                self._cx_spin.setRange(0.5, 0.5)
                self._cy_spin.setRange(0.5, 0.5)
            else:
                self._cx_spin.setRange(round(half, 4), round(1.0 - half, 4))
                self._cy_spin.setRange(round(half, 4), round(1.0 - half, 4))
        finally:
            self._emitting_guard = prev_guard
