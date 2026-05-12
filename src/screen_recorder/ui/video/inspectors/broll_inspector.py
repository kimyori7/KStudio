"""BrollInspector — broll(곁들임 영상) 효과 편집 폼.

ZoomInspector / SpeedInspector 패턴 답습 — `_emitting_guard` 로 set_effect 중에는
시그널을 무시하고, 위젯 변경 시 dataclasses.replace 로 새 BrollEffect 를 만들어
effect_changed 발화.

v1: PiP 만 미리보기/내보내기 지원.
- placement='pip' → corner radio + size combo 활성화
- placement='fullscreen' → PiP 위젯 비활성화 + 안내 라벨 (자르기+영상 끼워넣기 권장)
- audio_mix='original_only' 만 export 지원, 다른 모드는 폼에서 선택은 가능 (export 시 NotImplementedError).

'이 곁들임 삭제' 버튼은 effect_deleted(effect_id) 시그널 발화.
"""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QRadioButton, QSpinBox, QWidget,
)

from ....effects.types.broll import BrollEffect, PipConfig
from .base import InspectorBase


_VIDEO_FILTER = "Videos and images (*.mp4 *.mov *.avi *.gif *.png *.jpg *.jpeg)"
_ACCEPTED_SUFFIXES = {".mp4", ".mov", ".avi", ".gif", ".png", ".jpg", ".jpeg", ".mkv", ".webm"}


# ---- combo 매핑 ----
# placement 콤보 — 라벨 ↔ 값. 첫 항목이 v1 권장 (PiP).
_PLACEMENT_LABELS: list[tuple[str, str]] = [
    ("PiP (모서리 작게)",                  "pip"),
    ("전체 화면 (자르기 끼워넣기 권장)",   "fullscreen"),
]
_PLACEMENT_LABEL_TO_VALUE = {label: value for label, value in _PLACEMENT_LABELS}
_PLACEMENT_VALUE_TO_LABEL = {value: label for label, value in _PLACEMENT_LABELS}

# 모서리 라디오 — 라벨 ↔ 값.
_CORNER_LABELS: list[tuple[str, str]] = [
    ("좌상", "top-left"),
    ("우상", "top-right"),
    ("좌하", "bottom-left"),
    ("우하", "bottom-right"),
]
_CORNER_VALUE_TO_INDEX = {value: i for i, (_, value) in enumerate(_CORNER_LABELS)}

# 크기 콤보 — 라벨 ↔ ratio.
_SIZE_LABELS: list[tuple[str, float]] = [
    ("20%", 0.2),
    ("30%", 0.3),
    ("40%", 0.4),
]
_SIZE_RATIO_TO_LABEL = {ratio: label for label, ratio in _SIZE_LABELS}

# 오디오 믹스 콤보 — 라벨 ↔ 값.
_AUDIO_MIX_LABELS: list[tuple[str, str]] = [
    ("원본만",        "original_only"),
    ("broll만",       "broll_only"),
    ("둘 다 (믹스)",   "both"),
    ("음소거",        "mute"),
]
_AUDIO_MIX_LABEL_TO_VALUE = {label: value for label, value in _AUDIO_MIX_LABELS}
_AUDIO_MIX_VALUE_TO_LABEL = {value: label for label, value in _AUDIO_MIX_LABELS}


_FULLSCREEN_WARNING = (
    "전체화면은 v1 미리보기/내보내기 미지원 — 자르기(구간)+영상 끼워넣기를 사용하세요"
)


class BrollInspector(InspectorBase):
    """곁들임 영상 효과 편집 폼 (v1 — PiP only 활성)."""

    # InspectorBase 의 effect_changed 외에 effect_deleted 추가 (panel 이 bubble).
    effect_deleted = Signal(str)   # effect_id

    def __init__(self) -> None:
        super().__init__()
        self._emitting_guard: bool = False
        self._effect: Optional[BrollEffect] = None
        self._build_ui()
        self._set_form_enabled(False)
        # 외부(탐색기·라이브러리) 에서 mp4 를 드롭하면 src 설정.
        self.setAcceptDrops(True)

    # ---------- UI build ----------
    def _build_ui(self) -> None:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self._layout.addLayout(form)

        # ---- 파일 선택 ----
        src_row = QHBoxLayout()
        self._src_label = QLabel("(파일 없음)")
        self._src_label.setWordWrap(True)
        self._pick_btn = QPushButton("파일 선택…")
        self._pick_btn.clicked.connect(self._on_pick_clicked)
        src_row.addWidget(self._src_label, stretch=1)
        src_row.addWidget(self._pick_btn)
        form.addRow("파일", src_row)

        # 드래그 앤 드롭 안내 — 외부 탐색기/라이브러리에서 mp4 를 끌어 놓으면 자동으로 src 설정.
        self._dnd_hint_label = QLabel("💡 파일을 여기로 끌어 놓아도 됩니다")
        self._dnd_hint_label.setStyleSheet("color: #9ca3af; font-size: 10px;")
        form.addRow("", self._dnd_hint_label)

        # ---- placement 콤보 ----
        self._placement_combo = QComboBox()
        for label, _value in _PLACEMENT_LABELS:
            self._placement_combo.addItem(label)
        self._placement_combo.currentIndexChanged.connect(self._on_placement_change)
        form.addRow("배치", self._placement_combo)

        # 전체화면 경고 라벨 — placement='fullscreen' 일 때만 보임.
        self._fullscreen_warning_label = QLabel(_FULLSCREEN_WARNING)
        self._fullscreen_warning_label.setWordWrap(True)
        self._fullscreen_warning_label.setStyleSheet("color: #f59e0b;")   # 주황 경고
        self._fullscreen_warning_label.setVisible(False)
        form.addRow("", self._fullscreen_warning_label)

        # ---- 모서리 라디오 (PiP only) ----
        corner_row = QHBoxLayout()
        self._corner_group = QButtonGroup(self)
        self._corner_radios: list[QRadioButton] = []
        for idx, (label, value) in enumerate(_CORNER_LABELS):
            rb = QRadioButton(label)
            rb.setProperty("corner_value", value)
            self._corner_group.addButton(rb, idx)
            rb.toggled.connect(self._on_any_change)
            corner_row.addWidget(rb)
            self._corner_radios.append(rb)
        form.addRow("모서리", corner_row)

        # ---- 크기 콤보 (PiP only) ----
        self._size_combo = QComboBox()
        for label, _ratio in _SIZE_LABELS:
            self._size_combo.addItem(label)
        self._size_combo.currentIndexChanged.connect(self._on_any_change)
        form.addRow("크기", self._size_combo)

        # ---- 오디오 믹스 콤보 ----
        self._audio_mix_combo = QComboBox()
        for label, _value in _AUDIO_MIX_LABELS:
            self._audio_mix_combo.addItem(label)
        self._audio_mix_combo.currentIndexChanged.connect(self._on_any_change)
        self._audio_mix_combo.currentIndexChanged.connect(
            lambda _idx: self._update_audio_mix_warning()
        )
        form.addRow("오디오", self._audio_mix_combo)
        # 'original_only' 외 모드는 export v1 미지원 — 사용자 사전 경고. v2 audio
        # mixing 구현 전까지 visible.
        self._audio_mix_warning = QLabel(
            "⚠ '원본만' 외 모드는 내보내기 미지원 (v2 작업). 미리보기에선 작동."
        )
        self._audio_mix_warning.setStyleSheet("color: #f59e0b; font-size: 11px;")
        self._audio_mix_warning.setWordWrap(True)
        self._audio_mix_warning.setVisible(False)
        form.addRow("", self._audio_mix_warning)

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
        self._delete_btn = QPushButton("이 곁들임 삭제")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        form.addRow("", self._delete_btn)

        self._layout.addStretch(1)

    # ---------- public API ----------
    def set_effect(self, effect: Optional[BrollEffect]) -> None:
        """효과를 폼에 채워 넣음. None 이면 disable."""
        super().set_effect(effect)
        if effect is None:
            self._effect = None
            self._set_form_enabled(False)
            return
        if not isinstance(effect, BrollEffect):
            return
        self._emitting_guard = True
        try:
            self._effect = effect
            # src 라벨
            if effect.src:
                self._src_label.setText(Path(effect.src).name)
            else:
                self._src_label.setText("(파일 없음)")
            # placement 콤보
            placement_label = _PLACEMENT_VALUE_TO_LABEL.get(
                effect.placement, _PLACEMENT_LABELS[0][0],
            )
            self._placement_combo.setCurrentText(placement_label)
            # 모서리 라디오 — pip 가 있으면 그 값, 없으면 기본 'bottom-right'.
            corner = (effect.pip.corner if effect.pip is not None
                      else "bottom-right")
            corner_idx = _CORNER_VALUE_TO_INDEX.get(corner, 3)
            corner_btn = self._corner_group.button(corner_idx)
            if corner_btn is not None:
                corner_btn.setChecked(True)
            # 크기 콤보 — pip 가 있으면 그 ratio 에 가장 가까운 항목.
            ratio = (effect.pip.size_ratio if effect.pip is not None else 0.3)
            size_label = _SIZE_RATIO_TO_LABEL.get(round(ratio, 2))
            if size_label is None:
                # 임의 값 — 가장 가까운 항목 선택.
                size_label = min(
                    _SIZE_LABELS, key=lambda kv: abs(kv[1] - ratio),
                )[0]
            self._size_combo.setCurrentText(size_label)
            # audio_mix
            audio_label = _AUDIO_MIX_VALUE_TO_LABEL.get(
                effect.audio_mix, _AUDIO_MIX_LABELS[0][0],
            )
            self._audio_mix_combo.setCurrentText(audio_label)
            self._update_audio_mix_warning()
            # in / out
            self._in_spin.setValue(int(effect.in_ms))
            self._out_spin.setValue(int(effect.out_ms))
        finally:
            self._emitting_guard = False
        self._set_form_enabled(True)
        self._update_pip_widgets_enabled()

    # 별칭 — 일부 호출자가 load_effect 라는 이름을 기대할 수 있어 alias 제공.
    def load_effect(self, effect: Optional[BrollEffect]) -> None:
        self.set_effect(effect)

    # ---------- internal ----------
    def _set_form_enabled(self, enabled: bool) -> None:
        for w in (self._pick_btn, self._placement_combo, self._size_combo,
                  self._audio_mix_combo, self._in_spin, self._out_spin,
                  self._delete_btn):
            w.setEnabled(enabled)
        for rb in self._corner_radios:
            rb.setEnabled(enabled)

    def _current_placement(self) -> str:
        return _PLACEMENT_LABEL_TO_VALUE.get(
            self._placement_combo.currentText(), "pip",
        )

    def _current_corner(self) -> str:
        for rb in self._corner_radios:
            if rb.isChecked():
                return rb.property("corner_value") or "bottom-right"
        return "bottom-right"

    def _current_size_ratio(self) -> float:
        label = self._size_combo.currentText()
        for lbl, ratio in _SIZE_LABELS:
            if lbl == label:
                return ratio
        return 0.3

    def _current_audio_mix(self) -> str:
        return _AUDIO_MIX_LABEL_TO_VALUE.get(
            self._audio_mix_combo.currentText(), "original_only",
        )

    def _update_audio_mix_warning(self) -> None:
        """audio_mix 가 'original_only' 외면 노란 경고 라벨 표시."""
        if hasattr(self, "_audio_mix_warning"):
            self._audio_mix_warning.setVisible(
                self._current_audio_mix() != "original_only"
            )

    def _update_pip_widgets_enabled(self) -> None:
        """placement 에 따라 PiP 전용 위젯의 enable 상태 + 경고 라벨 표시 결정."""
        is_pip = (self._current_placement() == "pip")
        for rb in self._corner_radios:
            rb.setEnabled(is_pip)
        self._size_combo.setEnabled(is_pip)
        self._fullscreen_warning_label.setVisible(not is_pip)

    def _on_placement_change(self, *_) -> None:
        self._update_pip_widgets_enabled()
        self._on_any_change()

    def _on_any_change(self, *_) -> None:
        if self._emitting_guard or self._effect is None:
            return
        placement = self._current_placement()
        # in/out — 음수/역전 방지. Effect.__post_init__ 은 strict out > in 요구.
        in_ms = int(self._in_spin.value())
        out_ms = int(self._out_spin.value())
        if out_ms <= in_ms:
            out_ms = in_ms + 1
        # pip — placement="pip" 면 항상 PipConfig 채움. fullscreen 이면 None.
        pip: Optional[PipConfig] = None
        if placement == "pip":
            try:
                pip = PipConfig(
                    corner=self._current_corner(),
                    size_ratio=self._current_size_ratio(),
                )
            except ValueError:
                return
        try:
            new_eff = replace(
                self._effect,
                placement=placement,
                pip=pip,
                audio_mix=self._current_audio_mix(),
                in_ms=in_ms,
                out_ms=out_ms,
            )
        except ValueError:
            # BrollEffect __post_init__ 검증 실패 — 무시.
            return
        self._effect = new_eff
        self.effect_changed.emit(new_eff)

    def _on_pick_clicked(self) -> None:
        if self._effect is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "곁들임 영상/이미지 선택", "", _VIDEO_FILTER,
        )
        if not path:
            return
        try:
            new_eff = replace(self._effect, src=path)
        except ValueError:
            return
        self._effect = new_eff
        self._src_label.setText(Path(path).name)
        self.effect_changed.emit(new_eff)

    def _on_delete_clicked(self) -> None:
        if self._effect is None:
            return
        self.effect_deleted.emit(self._effect.id)

    # ---------- drag-and-drop ----------
    @staticmethod
    def _first_supported_path(urls) -> Optional[str]:
        for u in urls:
            if not u.isLocalFile():
                continue
            p = u.toLocalFile()
            if Path(p).suffix.lower() in _ACCEPTED_SUFFIXES:
                return p
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._effect is None:
            event.ignore()
            return
        md = event.mimeData()
        if md.hasUrls() and self._first_supported_path(md.urls()) is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if self._effect is None:
            event.ignore()
            return
        path = self._first_supported_path(event.mimeData().urls())
        if path is None:
            event.ignore()
            return
        try:
            new_eff = replace(self._effect, src=path)
        except ValueError:
            event.ignore()
            return
        self._effect = new_eff
        self._src_label.setText(Path(path).name)
        self.effect_changed.emit(new_eff)
        event.acceptProposedAction()
