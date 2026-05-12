"""SpeedInspector — 배속 효과 편집 폼.

CaptionInspector / CutInspector 패턴 답습 — `_emitting_guard` 로 set_effect 중에는
시그널을 무시하고, 위젯 변경 시 dataclasses.replace 로 새 SpeedEffect 를 만들어
effect_changed 발화. 'rate' 는 QDoubleSpinBox (0.1~32.0, step 0.25). 'audio' 콤보는
자동/음소거/atempo 매핑. '이 배속 삭제' 버튼은 effect_deleted(effect_id) 발화.

이전: rate 가 콤보 + 사용자 지정 다이얼로그였는데, "사용자 지정 콤보 재선택해도 팝업
안 뜸" 회귀 + 임의 입력의 번거로움. spinbox 로 통일 — 화살표 0.25 step + 직접 입력.
"""
from __future__ import annotations
from dataclasses import replace
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QPushButton, QSpinBox,
)

from ....effects.types.speed import SpeedEffect
from .base import InspectorBase


# audio 콤보 — 라벨 ↔ enum 값 양방향.
_AUDIO_LABELS: list[tuple[str, str]] = [
    ("자동", "auto"),
    ("음소거", "mute"),
    ("음성도 같이 (atempo)", "atempo"),
]
_AUDIO_LABEL_TO_VALUE = {label: value for label, value in _AUDIO_LABELS}
_AUDIO_VALUE_TO_LABEL = {value: label for label, value in _AUDIO_LABELS}


class SpeedInspector(InspectorBase):
    """배속 효과 편집 폼."""

    # InspectorBase 의 effect_changed 외에 effect_deleted 추가 (panel 이 bubble).
    effect_deleted = Signal(str)   # effect_id

    def __init__(self) -> None:
        super().__init__()
        self._emitting_guard: bool = False
        self._effect: Optional[SpeedEffect] = None
        self._build_ui()
        self._set_form_enabled(False)

    # ---------- UI build ----------
    def _build_ui(self) -> None:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self._layout.addLayout(form)

        # ---- rate ---- QDoubleSpinBox (0.1~32.0, step 0.25, suffix ×)
        self._rate_spin = QDoubleSpinBox()
        self._rate_spin.setRange(0.1, 32.0)
        self._rate_spin.setSingleStep(0.25)
        self._rate_spin.setDecimals(2)
        self._rate_spin.setSuffix(" ×")
        self._rate_spin.setValue(1.0)
        self._rate_spin.valueChanged.connect(self._on_any_change)
        form.addRow("배속", self._rate_spin)

        # ---- audio ----
        self._audio_combo = QComboBox()
        for label, _value in _AUDIO_LABELS:
            self._audio_combo.addItem(label)
        self._audio_combo.currentIndexChanged.connect(self._on_any_change)
        form.addRow("오디오", self._audio_combo)

        # ---- HUD ----
        self._show_hud_check = QCheckBox("배속 HUD 표시")
        self._show_hud_check.toggled.connect(self._on_any_change)
        form.addRow("", self._show_hud_check)

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

        # ---- 삭제 버튼 ----
        self._delete_btn = QPushButton("이 배속 삭제")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        form.addRow("", self._delete_btn)

        self._layout.addStretch(1)

    # ---------- public API ----------
    def set_effect(self, effect: Optional[SpeedEffect]) -> None:
        """효과를 폼에 채워 넣음. None 이면 disable."""
        super().set_effect(effect)
        if effect is None:
            self._effect = None
            self._set_form_enabled(False)
            return
        if not isinstance(effect, SpeedEffect):
            return
        self._emitting_guard = True
        try:
            self._effect = effect
            self._rate_spin.setValue(float(effect.rate))
            # audio 콤보
            label = _AUDIO_VALUE_TO_LABEL.get(effect.audio, _AUDIO_LABELS[0][0])
            self._audio_combo.setCurrentText(label)
            # show_hud
            self._show_hud_check.setChecked(effect.show_hud)
            # in / out
            self._in_spin.setValue(int(effect.in_ms))
            self._out_spin.setValue(int(effect.out_ms))
        finally:
            self._emitting_guard = False
        self._set_form_enabled(True)

    # 별칭 — 일부 호출자가 load_effect 라는 이름을 기대할 수 있어 alias 제공.
    def load_effect(self, effect: Optional[SpeedEffect]) -> None:
        self.set_effect(effect)

    # ---------- internal ----------
    def _set_form_enabled(self, enabled: bool) -> None:
        for w in (self._rate_spin, self._audio_combo, self._show_hud_check,
                  self._in_spin, self._out_spin, self._delete_btn):
            w.setEnabled(enabled)

    def _on_any_change(self, *_) -> None:
        if self._emitting_guard or self._effect is None:
            return
        rate = float(self._rate_spin.value())
        # audio — 라벨 → enum 값
        audio_label = self._audio_combo.currentText()
        audio = _AUDIO_LABEL_TO_VALUE.get(audio_label, "auto")
        # in/out — 음수/역전 방지. Effect.__post_init__ 은 strict out > in 요구.
        in_ms = int(self._in_spin.value())
        out_ms = int(self._out_spin.value())
        if out_ms <= in_ms:
            out_ms = in_ms + 1
        try:
            new_eff = replace(
                self._effect,
                rate=rate,
                audio=audio,
                show_hud=self._show_hud_check.isChecked(),
                in_ms=in_ms,
                out_ms=out_ms,
            )
        except ValueError:
            # SpeedEffect.__post_init__ 검증 실패 (rate 범위 등) — 무시.
            return
        self._effect = new_eff
        self.effect_changed.emit(new_eff)

    def _on_delete_clicked(self) -> None:
        if self._effect is None:
            return
        self.effect_deleted.emit(self._effect.id)
