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
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QPushButton, QRadioButton, QSpinBox, QToolButton, QWidget,
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
        self._form = form
        # Phase 28 — "수치 입력" 접기 그룹. 평상시엔 화면 위 가이드 박스로 조정하면 충분.
        # 보관: 9개 입력의 spinbox 참조. 토글 시 일괄 hide/show.
        self._numeric_fields: list = []

        # ---- mode 라디오 (Phase 24): fit_screen / magnify_region ----
        mode_row = QWidget()
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(8)
        self._mode_fit = QRadioButton("전체 화면 확대")
        self._mode_magnify = QRadioButton("부분 영역만 확대")
        self._mode_fit.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._mode_fit, 0)
        self._mode_group.addButton(self._mode_magnify, 1)
        self._mode_fit.toggled.connect(self._on_mode_toggled)
        mode_layout.addWidget(self._mode_fit)
        mode_layout.addWidget(self._mode_magnify)
        mode_layout.addStretch(1)
        form.addRow("모드", mode_row)

        # ---- 미리보기 체크박스 (Phase 28 — 모드 바로 밑, 자주 쓰는 위치) ----
        self._preview_chk = QCheckBox("이 줌 구간 재생 시 화면 줌인 적용")
        self._preview_chk.toggled.connect(self._on_any_change)
        form.addRow("미리보기", self._preview_chk)

        # ---- 수치 입력 접기 그룹 토글 버튼 (Phase 28) ----
        self._numeric_toggle = QToolButton()
        self._numeric_toggle.setText("▶ 수치 입력 (펼치기)")
        self._numeric_toggle.setCheckable(True)
        self._numeric_toggle.setChecked(False)
        self._numeric_toggle.setStyleSheet("text-align: left; padding: 4px;")
        self._numeric_toggle.toggled.connect(self._on_numeric_toggle)
        form.addRow("", self._numeric_toggle)

        # ---- cx ----
        self._cx_spin = QDoubleSpinBox()
        self._cx_spin.setRange(0.0, 1.0)
        self._cx_spin.setSingleStep(0.05)
        self._cx_spin.setDecimals(2)
        self._cx_spin.valueChanged.connect(self._on_any_change)
        form.addRow("중심 X (0~1)", self._cx_spin)
        self._numeric_fields.append(self._cx_spin)

        # ---- cy ----
        self._cy_spin = QDoubleSpinBox()
        self._cy_spin.setRange(0.0, 1.0)
        self._cy_spin.setSingleStep(0.05)
        self._cy_spin.setDecimals(2)
        self._cy_spin.valueChanged.connect(self._on_any_change)
        form.addRow("중심 Y (0~1)", self._cy_spin)
        self._numeric_fields.append(self._cy_spin)

        # ---- scale ----
        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(0.1, 10.0)
        self._scale_spin.setSingleStep(0.5)
        self._scale_spin.setDecimals(2)
        self._scale_spin.setSuffix("×")
        self._scale_spin.valueChanged.connect(self._on_any_change)
        form.addRow("배율", self._scale_spin)
        self._numeric_fields.append(self._scale_spin)

        # ---- region_w / region_h (magnify_region 전용 — source 영역) ----
        self._region_w_spin = QDoubleSpinBox()
        self._region_w_spin.setRange(0.05, 1.0)
        self._region_w_spin.setSingleStep(0.05)
        self._region_w_spin.setDecimals(2)
        self._region_w_spin.setValue(0.3)
        self._region_w_spin.valueChanged.connect(self._on_any_change)
        self._region_w_label_text = "원본 폭 (0~1)"
        form.addRow(self._region_w_label_text, self._region_w_spin)
        self._numeric_fields.append(self._region_w_spin)

        self._region_h_spin = QDoubleSpinBox()
        self._region_h_spin.setRange(0.05, 1.0)
        self._region_h_spin.setSingleStep(0.05)
        self._region_h_spin.setDecimals(2)
        self._region_h_spin.setValue(0.3)
        self._region_h_spin.valueChanged.connect(self._on_any_change)
        self._region_h_label_text = "원본 높이 (0~1)"
        form.addRow(self._region_h_label_text, self._region_h_spin)
        self._numeric_fields.append(self._region_h_spin)

        # ---- dest_cx / dest_cy / dest_w / dest_h (Phase 27 — 확대 후 영역, 별도 조정) ----
        self._dest_cx_spin = QDoubleSpinBox()
        self._dest_cx_spin.setRange(0.0, 1.0)
        self._dest_cx_spin.setSingleStep(0.05)
        self._dest_cx_spin.setDecimals(2)
        self._dest_cx_spin.setValue(0.5)
        self._dest_cx_spin.valueChanged.connect(self._on_any_change)
        form.addRow("확대 후 중심 X", self._dest_cx_spin)
        self._numeric_fields.append(self._dest_cx_spin)

        self._dest_cy_spin = QDoubleSpinBox()
        self._dest_cy_spin.setRange(0.0, 1.0)
        self._dest_cy_spin.setSingleStep(0.05)
        self._dest_cy_spin.setDecimals(2)
        self._dest_cy_spin.setValue(0.5)
        self._dest_cy_spin.valueChanged.connect(self._on_any_change)
        form.addRow("확대 후 중심 Y", self._dest_cy_spin)
        self._numeric_fields.append(self._dest_cy_spin)

        self._dest_w_spin = QDoubleSpinBox()
        self._dest_w_spin.setRange(0.05, 2.0)
        self._dest_w_spin.setSingleStep(0.05)
        self._dest_w_spin.setDecimals(2)
        self._dest_w_spin.setValue(0.6)
        self._dest_w_spin.valueChanged.connect(self._on_any_change)
        form.addRow("확대 후 폭", self._dest_w_spin)
        self._numeric_fields.append(self._dest_w_spin)

        self._dest_h_spin = QDoubleSpinBox()
        self._dest_h_spin.setRange(0.05, 2.0)
        self._dest_h_spin.setSingleStep(0.05)
        self._dest_h_spin.setDecimals(2)
        self._dest_h_spin.setValue(0.6)
        self._dest_h_spin.valueChanged.connect(self._on_any_change)
        form.addRow("확대 후 높이", self._dest_h_spin)
        self._numeric_fields.append(self._dest_h_spin)

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

        # ---- 삭제 버튼 ----
        self._delete_btn = QPushButton("이 줌 삭제")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        form.addRow("", self._delete_btn)

        self._layout.addStretch(1)

        # 초기 — 수치 입력 9개 모두 접힘.
        self._apply_numeric_visible(False)

    # ---------- 접기 그룹 ----------
    def _on_numeric_toggle(self, checked: bool) -> None:
        self._numeric_toggle.setText(
            "▼ 수치 입력 (접기)" if checked else "▶ 수치 입력 (펼치기)"
        )
        self._apply_numeric_visible(checked)

    def _apply_numeric_visible(self, visible: bool) -> None:
        """9개 spinbox + form 의 label 함께 hide/show. magnify 모드에선 region/dest 6개만
        visible 상태 추가 제어 (_update_region_widgets_visibility) — 접힘 우선."""
        for w in self._numeric_fields:
            w.setVisible(visible)
            label_w = self._form.labelForField(w)
            if label_w is not None:
                label_w.setVisible(visible)
        # 펼친 직후 magnify 모드 시 region/dest 가시성 다시 적용.
        if visible and getattr(self, "_mode_magnify", None) is not None:
            self._update_region_widgets_visibility(self._mode_magnify.isChecked())

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
            mode = getattr(effect, "mode", "fit_screen")
            self._mode_fit.setChecked(mode == "fit_screen")
            self._mode_magnify.setChecked(mode == "magnify_region")
            self._update_cx_cy_range_for_mode(
                mode, float(effect.start.scale),
                float(getattr(effect, "region_w", 0.3)),
                float(getattr(effect, "region_h", 0.3)),
            )
            self._cx_spin.setValue(float(effect.start.cx))
            self._cy_spin.setValue(float(effect.start.cy))
            self._scale_spin.setValue(float(effect.start.scale))
            self._region_w_spin.setValue(float(getattr(effect, "region_w", 0.3)))
            self._region_h_spin.setValue(float(getattr(effect, "region_h", 0.3)))
            self._dest_cx_spin.setValue(float(getattr(effect, "dest_cx", 0.5)))
            self._dest_cy_spin.setValue(float(getattr(effect, "dest_cy", 0.5)))
            self._dest_w_spin.setValue(float(getattr(effect, "dest_w", 0.6)))
            self._dest_h_spin.setValue(float(getattr(effect, "dest_h", 0.6)))
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
            # region 위젯 visibility — magnify_region 모드에서만 의미 있음.
            self._update_region_widgets_visibility(mode == "magnify_region")
        finally:
            self._emitting_guard = False
        self._set_form_enabled(True)

    # 별칭 — 일부 호출자가 load_effect 라는 이름을 기대할 수 있어 alias 제공.
    def load_effect(self, effect: Optional[ZoomEffect]) -> None:
        self.set_effect(effect)

    # ---------- internal ----------
    def _set_form_enabled(self, enabled: bool) -> None:
        for w in (self._mode_fit, self._mode_magnify,
                  self._cx_spin, self._cy_spin, self._scale_spin,
                  self._region_w_spin, self._region_h_spin,
                  self._dest_cx_spin, self._dest_cy_spin,
                  self._dest_w_spin, self._dest_h_spin,
                  self._ease_combo, self._in_anim_spin, self._out_anim_spin,
                  self._in_spin, self._out_spin, self._preview_chk, self._delete_btn):
            w.setEnabled(enabled)

    def _on_mode_toggled(self, _checked: bool) -> None:
        if self._emitting_guard:
            return
        is_magnify = self._mode_magnify.isChecked()
        self._update_region_widgets_visibility(is_magnify)
        self._on_any_change()

    def _update_region_widgets_visibility(self, magnify: bool) -> None:
        """region_*/dest_* 입력은 magnify_region 모드에서만. 접기 그룹이 닫혀 있으면 무조건 hide.

        Phase 28 — 수치 입력 그룹 토글 우선. 접힘 상태면 mode 와 무관하게 모두 hide.
        """
        group_open = getattr(self, "_numeric_toggle", None) is not None and \
                     self._numeric_toggle.isChecked()
        show_region = magnify and group_open
        for w in (self._region_w_spin, self._region_h_spin,
                  self._dest_cx_spin, self._dest_cy_spin,
                  self._dest_w_spin, self._dest_h_spin):
            w.setVisible(show_region)
            label_w = self._form.labelForField(w)
            if label_w is not None:
                label_w.setVisible(show_region)

    def _on_any_change(self, *_) -> None:
        if self._emitting_guard or self._effect is None:
            return
        scale = float(self._scale_spin.value())
        mode = "magnify_region" if self._mode_magnify.isChecked() else "fit_screen"
        region_w = float(self._region_w_spin.value())
        region_h = float(self._region_h_spin.value())
        # mode 에 따라 cx/cy 의 valid range 갱신 — 가장자리 over-shoot 방지.
        self._update_cx_cy_range_for_mode(mode, scale, region_w, region_h)
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
        dest_cx = float(self._dest_cx_spin.value())
        dest_cy = float(self._dest_cy_spin.value())
        dest_w = float(self._dest_w_spin.value())
        dest_h = float(self._dest_h_spin.value())
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
                mode=mode,
                region_w=region_w,
                region_h=region_h,
                dest_cx=dest_cx,
                dest_cy=dest_cy,
                dest_w=dest_w,
                dest_h=dest_h,
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
        """기존 호환용 — fit_screen 모드 기준 cx/cy range 갱신."""
        self._update_cx_cy_range_for_mode("fit_screen", scale, 0.3, 0.3)

    def _update_cx_cy_range_for_mode(self, mode: str, scale: float,
                                      region_w: float, region_h: float) -> None:
        """모드별 cx/cy 의 valid range 갱신.

        fit_screen: source = 1/scale × 1/scale → half = 0.5 / scale.
        magnify_region: source = region_w × region_h → half = region/2. (dest 가 화면
            밖으로 나가는 건 허용 — overlay 가 자동 clip.)
        """
        if mode == "magnify_region":
            half_x = max(0.025, region_w / 2.0)
            half_y = max(0.025, region_h / 2.0)
        else:
            half_x = 0.5 / max(0.1, scale)
            half_y = half_x
        prev_guard = self._emitting_guard
        self._emitting_guard = True
        try:
            if half_x >= 0.5:
                self._cx_spin.setRange(0.5, 0.5)
            else:
                self._cx_spin.setRange(round(half_x, 4), round(1.0 - half_x, 4))
            if half_y >= 0.5:
                self._cy_spin.setRange(0.5, 0.5)
            else:
                self._cy_spin.setRange(round(half_y, 4), round(1.0 - half_y, 4))
        finally:
            self._emitting_guard = prev_guard
