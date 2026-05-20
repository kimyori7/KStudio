"""AudioExportSettingsDialog — 음성 export 형식/채널/샘플링 선택.

2026-05-20 신규 (사용자 요청). 진행 표시는 별도로 기존 ExportDialog 재사용.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QRadioButton, QVBoxLayout,
)

from ..encode.audio_export import AudioExportSettings


_SAMPLE_RATE_LABELS = [
    ("22050 Hz", 22050),
    ("44100 Hz", 44100),
    ("48000 Hz", 48000),
]
_BITRATE_LABELS = [
    ("128 kbps", 128),
    ("192 kbps", 192),
    ("320 kbps", 320),
]


class AudioExportSettingsDialog(QDialog):
    """음성 export 설정 다이얼로그.

    OK 누르면 accept(), `current_settings()` 가 선택된 AudioExportSettings 반환.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("음성 내보내기")
        self.setModal(True)
        self.resize(360, 220)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        # ---- 형식 ----
        self.mp3_radio = QRadioButton("MP3 (압축)")
        self.wav_radio = QRadioButton("WAV (무손실)")
        self.mp3_radio.setChecked(True)
        self._format_group = QButtonGroup(self)
        self._format_group.addButton(self.mp3_radio)
        self._format_group.addButton(self.wav_radio)
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(self.mp3_radio)
        fmt_row.addWidget(self.wav_radio)
        fmt_row.addStretch(1)
        form.addRow("형식", fmt_row)

        # ---- 채널 ----
        self.stereo_radio = QRadioButton("스테레오 (2채널)")
        self.mono_radio = QRadioButton("모노 (1채널)")
        self.stereo_radio.setChecked(True)
        self._channels_group = QButtonGroup(self)
        self._channels_group.addButton(self.stereo_radio)
        self._channels_group.addButton(self.mono_radio)
        ch_row = QHBoxLayout()
        ch_row.addWidget(self.stereo_radio)
        ch_row.addWidget(self.mono_radio)
        ch_row.addStretch(1)
        form.addRow("채널", ch_row)

        # ---- 샘플링 ----
        self.sample_rate_combo = QComboBox()
        for label, _val in _SAMPLE_RATE_LABELS:
            self.sample_rate_combo.addItem(label)
        self.sample_rate_combo.setCurrentText("44100 Hz")
        form.addRow("샘플링", self.sample_rate_combo)

        # ---- MP3 비트레이트 (MP3 일 때만 의미) ----
        self.bitrate_combo = QComboBox()
        for label, _val in _BITRATE_LABELS:
            self.bitrate_combo.addItem(label)
        self.bitrate_combo.setCurrentText("192 kbps")
        form.addRow("MP3 비트레이트", self.bitrate_combo)

        # WAV 선택 시 비트레이트 콤보 비활성 — 의미 없으므로 시각적 가이드.
        self.mp3_radio.toggled.connect(self._sync_bitrate_enabled)
        self._sync_bitrate_enabled(self.mp3_radio.isChecked())

        # ---- 안내 ----
        hint = QLabel(
            "사이드카의 자르기(cut) 가 반영됩니다. 배속/줌 등은 v1 에서 미반영."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        layout.addWidget(hint)

        # ---- 버튼 ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        buttons.button(QDialogButtonBox.Ok).setText("내보내기")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ---------- API ----------
    def current_settings(self) -> AudioExportSettings:
        fmt = "mp3" if self.mp3_radio.isChecked() else "wav"
        ch = 2 if self.stereo_radio.isChecked() else 1
        sr_label = self.sample_rate_combo.currentText()
        sr = next(v for label, v in _SAMPLE_RATE_LABELS if label == sr_label)
        br_label = self.bitrate_combo.currentText()
        br = next(v for label, v in _BITRATE_LABELS if label == br_label)
        return AudioExportSettings(
            format=fmt, channels=ch, sample_rate=sr, mp3_bitrate=br,
        )

    def suggested_extension(self) -> str:
        return ".mp3" if self.mp3_radio.isChecked() else ".wav"

    # ---------- internal ----------
    def _sync_bitrate_enabled(self, mp3_on: bool) -> None:
        self.bitrate_combo.setEnabled(bool(mp3_on))
