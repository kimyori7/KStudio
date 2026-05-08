"""SpeedInspector — 배속 효과 편집 폼.

CaptionInspector / CutInspector 패턴 답습 — `_emitting_guard` 로 set_effect 중에는
시그널을 무시하고, 위젯 변경 시 dataclasses.replace 로 새 SpeedEffect 를 만들어
effect_changed 발화. 'rate' 콤보의 마지막 항목 '사용자 지정…' 은 QInputDialog 로
임의 배율 입력. 'audio' 콤보는 자동/음소거/atempo 매핑.
'이 배속 삭제' 버튼은 effect_deleted(effect_id) 시그널 발화.
"""
from __future__ import annotations
from dataclasses import replace
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QPushButton, QSpinBox, QWidget,
)

from ....effects.types.speed import SpeedEffect
from .base import InspectorBase


# ---- combo 매핑 ----
# rate 콤보 — 미리 정의된 프리셋 + 마지막 '사용자 지정…' 항목.
_RATE_PRESETS: list[float] = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 5.0]
_CUSTOM_LABEL = "사용자 지정…"

# audio 콤보 — 라벨 ↔ enum 값 양방향.
_AUDIO_LABELS: list[tuple[str, str]] = [
    ("자동", "auto"),
    ("음소거", "mute"),
    ("음성도 같이 (atempo)", "atempo"),
]
_AUDIO_LABEL_TO_VALUE = {label: value for label, value in _AUDIO_LABELS}
_AUDIO_VALUE_TO_LABEL = {value: label for label, value in _AUDIO_LABELS}


def _format_rate(rate: float) -> str:
    """1.0 → '1.0×', 0.75 → '0.75×', 2.0 → '2.0×'. 콤보 라벨 통일."""
    return f"{rate:g}×"


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

        # ---- rate ----
        self._rate_combo = QComboBox()
        for r in _RATE_PRESETS:
            self._rate_combo.addItem(_format_rate(r), userData=r)
        self._rate_combo.addItem(_CUSTOM_LABEL, userData=None)
        self._rate_combo.currentIndexChanged.connect(self._on_rate_combo_changed)
        form.addRow("배속", self._rate_combo)

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
            # rate 콤보 — 프리셋 매칭이면 그 인덱스, 아니면 '사용자 지정…' 라벨에
            # 현재 값 표시 (선택은 마지막 항목으로).
            self._select_rate_in_combo(effect.rate)
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
        for w in (self._rate_combo, self._audio_combo, self._show_hud_check,
                  self._in_spin, self._out_spin, self._delete_btn):
            w.setEnabled(enabled)

    def _select_rate_in_combo(self, rate: float) -> None:
        """프리셋과 매칭되는 항목이 있으면 그것을, 없으면 마지막 '사용자 지정…' 항목 라벨에
        현재 값을 끼워 넣어 선택한다 (사용자 입력값을 잃지 않도록).
        """
        for i, preset in enumerate(_RATE_PRESETS):
            if abs(preset - rate) < 1e-6:
                self._rate_combo.setCurrentIndex(i)
                return
        # 비프리셋 — 마지막 항목 라벨에 현재 값 표시. userData 도 갱신.
        last = self._rate_combo.count() - 1
        self._rate_combo.setItemText(last, f"{_CUSTOM_LABEL} ({rate:g}×)")
        self._rate_combo.setItemData(last, rate)
        self._rate_combo.setCurrentIndex(last)

    def _on_rate_combo_changed(self, index: int) -> None:
        if self._emitting_guard or self._effect is None:
            return
        # 마지막 항목('사용자 지정…') 선택 시: getDouble 로 값 받기, 사용자가 취소하면
        # 이전 값으로 되돌림.
        if index == self._rate_combo.count() - 1 and self._rate_combo.itemData(index) is None:
            value, ok = QInputDialog.getDouble(
                self, "사용자 지정 배속", "배속 (0.1 ~ 32.0):",
                value=self._effect.rate, minValue=0.1, maxValue=32.0, decimals=2,
            )
            if not ok:
                # 취소 — 콤보 선택을 원래 효과의 rate 로 복원.
                self._emitting_guard = True
                try:
                    self._select_rate_in_combo(self._effect.rate)
                finally:
                    self._emitting_guard = False
                return
            # 사용자 입력값을 마지막 항목의 라벨/데이터로 반영.
            self._emitting_guard = True
            try:
                last = self._rate_combo.count() - 1
                self._rate_combo.setItemText(last, f"{_CUSTOM_LABEL} ({value:g}×)")
                self._rate_combo.setItemData(last, value)
            finally:
                self._emitting_guard = False
        self._on_any_change()

    def _on_any_change(self, *_) -> None:
        if self._emitting_guard or self._effect is None:
            return
        # rate
        rate_data = self._rate_combo.currentData()
        rate = float(rate_data) if rate_data is not None else self._effect.rate
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
