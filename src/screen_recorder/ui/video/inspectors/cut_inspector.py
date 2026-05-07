"""CutInspector — cut 효과 편집 폼.

값이 바뀔 때마다 dataclass.replace 로 새 CutEffect 를 만들어 effect_changed 발화.
_emitting_guard 로 set_effect 중에는 시그널을 무시.

src 의 영상 길이는 ffprobe 로 확인 — `probe_duration_ms` 헬퍼 (테스트는 monkeypatch).
"""
from __future__ import annotations
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
)

from ....effects.types.cut import CutEffect
from .base import InspectorBase


_VIDEO_EXTS = "Video Files (*.mp4 *.mov *.mkv *.webm *.avi *.gif)"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def probe_duration_ms(path: str) -> int:
    """ffprobe 로 영상 길이를 ms 로. 실패하면 0.

    KStudio 환경: ffmpeg/ffprobe 가 PATH 또는 dist 번들에 있다고 가정.
    실패는 silent — UI 는 src_duration_ms == 0 인 채로 두고, 저장은 진행.
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
        if out.returncode != 0:
            return 0
        return int(float(out.stdout.strip()) * 1000)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


class CutInspector(InspectorBase):
    """cut 효과 편집 폼."""

    def __init__(self) -> None:
        super().__init__()
        self._emitting_guard: bool = False
        self._effect: Optional[CutEffect] = None
        self._has_src: bool = False
        self._build_ui()

    # ---------- UI build ----------
    def _build_ui(self) -> None:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self._layout.addLayout(form)

        # ---- A 자르기 구간 ----
        self.splice_check = QCheckBox("현재 시점 (splice point)")
        self.splice_check.toggled.connect(self._on_splice_toggle)
        form.addRow("", self.splice_check)

        in_row = QHBoxLayout()
        self.in_ms_spin = QSpinBox()
        self.in_ms_spin.setRange(0, 24 * 3600 * 1000)
        self.in_ms_spin.setSuffix(" ms")
        self.in_ms_spin.valueChanged.connect(self._on_any_change)
        in_row.addWidget(self.in_ms_spin)
        form.addRow("자르기 시작", in_row)

        out_row = QHBoxLayout()
        self.out_ms_spin = QSpinBox()
        self.out_ms_spin.setRange(0, 24 * 3600 * 1000)
        self.out_ms_spin.setSuffix(" ms")
        self.out_ms_spin.valueChanged.connect(self._on_any_change)
        out_row.addWidget(self.out_ms_spin)
        form.addRow("자르기 끝", out_row)

        # ---- B 영상 끼워넣기 (옵션) ----
        self.add_video_btn = QPushButton("+ 영상 넣기")
        self.add_video_btn.clicked.connect(self._pick_video)
        form.addRow("", self.add_video_btn)

        self._src_section = QWidget()
        src_layout = QFormLayout(self._src_section)
        src_layout.setContentsMargins(0, 0, 0, 0)
        self.src_path_label = QLabel("")
        self.src_path_label.setWordWrap(True)
        src_layout.addRow("파일", self.src_path_label)

        self.change_src_btn = QPushButton("파일 변경")
        self.change_src_btn.clicked.connect(self._pick_video)
        self.remove_src_btn = QPushButton("영상 제거")
        self.remove_src_btn.clicked.connect(self._remove_src)
        change_row = QHBoxLayout()
        change_row.addWidget(self.change_src_btn)
        change_row.addWidget(self.remove_src_btn)
        src_layout.addRow("", change_row)

        self.src_in_ms_spin = QSpinBox()
        self.src_in_ms_spin.setRange(0, 24 * 3600 * 1000)
        self.src_in_ms_spin.setSuffix(" ms")
        self.src_in_ms_spin.valueChanged.connect(self._on_any_change)
        src_layout.addRow("B 트림 시작", self.src_in_ms_spin)

        self.src_out_ms_spin = QSpinBox()
        self.src_out_ms_spin.setRange(0, 24 * 3600 * 1000)
        self.src_out_ms_spin.setSuffix(" ms (0=끝까지)")
        self.src_out_ms_spin.valueChanged.connect(self._on_any_change)
        src_layout.addRow("B 트림 끝", self.src_out_ms_spin)

        scale_row = QHBoxLayout()
        self.scale_mode_group = QButtonGroup(self)
        for idx, (key, label) in enumerate([("fit", "맞춤 (검은 여백)"),
                                            ("fill", "채움 (자르기)"),
                                            ("stretch", "늘리기")]):
            rb = QRadioButton(label)
            rb.setProperty("scale_mode", key)
            self.scale_mode_group.addButton(rb, idx)
            rb.toggled.connect(self._on_any_change)
            scale_row.addWidget(rb)
        src_layout.addRow("결합 모드", scale_row)

        form.addRow("", self._src_section)

        # ---- 결합 후 길이 ----
        self.combined_label = QLabel("")
        form.addRow("결합 후", self.combined_label)

    # ---------- public API ----------
    def has_src_section(self) -> bool:
        return self._src_section.isVisible()

    def set_effect(self, effect: CutEffect) -> None:
        if not isinstance(effect, CutEffect):
            return
        self._emitting_guard = True
        try:
            self._effect = effect
            self.in_ms_spin.setValue(effect.in_ms)
            self.out_ms_spin.setValue(effect.out_ms)
            self.splice_check.setChecked(effect.is_splice)
            self.out_ms_spin.setEnabled(not effect.is_splice)
            self._has_src = effect.has_insert
            self._src_section.setVisible(effect.has_insert)
            self.add_video_btn.setVisible(not effect.has_insert)
            if effect.has_insert:
                self.src_path_label.setText(effect.src)
                self.src_in_ms_spin.setValue(effect.src_in_ms)
                self.src_out_ms_spin.setValue(effect.src_out_ms)
                # scale_mode → 라디오 인덱스
                idx = {"fit": 0, "fill": 1, "stretch": 2}.get(effect.scale_mode, 0)
                btn = self.scale_mode_group.button(idx)
                if btn is not None:
                    btn.setChecked(True)
            self._update_combined_label()
        finally:
            self._emitting_guard = False

    # ---------- helpers ----------
    def _on_splice_toggle(self, checked: bool) -> None:
        if self._emitting_guard or self._effect is None:
            return
        self.out_ms_spin.setEnabled(not checked)
        if checked:
            self.out_ms_spin.setValue(self.in_ms_spin.value())
        self._on_any_change()

    def _on_any_change(self, *_) -> None:
        if self._emitting_guard or self._effect is None:
            return
        in_ms = self.in_ms_spin.value()
        out_ms = self.in_ms_spin.value() if self.splice_check.isChecked() else self.out_ms_spin.value()
        if out_ms < in_ms:
            out_ms = in_ms
        scale_mode = "fit"
        checked_id = self.scale_mode_group.checkedId()
        if checked_id >= 0:
            btn = self.scale_mode_group.button(checked_id)
            scale_mode = btn.property("scale_mode") or "fit"
        new_eff = replace(
            self._effect,
            in_ms=in_ms,
            out_ms=out_ms,
            src_in_ms=self.src_in_ms_spin.value() if self._has_src else 0,
            src_out_ms=self.src_out_ms_spin.value() if self._has_src else 0,
            scale_mode=scale_mode,
        )
        self._effect = new_eff
        self._update_combined_label()
        self.effect_changed.emit(new_eff)

    def _pick_video(self) -> None:
        if self._effect is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "영상 선택", "", _VIDEO_EXTS)
        if not path:
            return
        duration = probe_duration_ms(path)
        new_eff = replace(
            self._effect,
            src=path,
            src_duration_ms=duration,
            src_in_ms=0,
            src_out_ms=0,
        )
        self._effect = new_eff
        # UI 갱신 (set_effect 다시 호출)
        self.set_effect(new_eff)
        self.effect_changed.emit(new_eff)

    def _remove_src(self) -> None:
        if self._effect is None:
            return
        new_eff = replace(
            self._effect,
            src="",
            src_in_ms=0,
            src_out_ms=0,
            src_duration_ms=0,
            scale_mode="fit",
        )
        self._effect = new_eff
        self.set_effect(new_eff)
        self.effect_changed.emit(new_eff)

    def _update_combined_label(self) -> None:
        if self._effect is None:
            self.combined_label.setText("")
            return
        cut_len = self._effect.out_ms - self._effect.in_ms
        ins_len = self._effect.insert_duration_ms
        delta = ins_len - cut_len
        sign = "+" if delta >= 0 else ""
        self.combined_label.setText(f"시간축 변화: {sign}{delta / 1000.0:.1f}s")
