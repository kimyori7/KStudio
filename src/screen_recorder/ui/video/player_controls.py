"""곰/팟플레이어 스타일 영상 컨트롤 바."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QSlider, QComboBox,
)


_SPEEDS = [("0.5×", 0.5), ("1.0×", 1.0), ("1.5×", 1.5), ("2.0×", 2.0)]


def _format_ms(ms: int) -> str:
    s = max(0, ms // 1000)
    return f"{s // 60:02d}:{s % 60:02d}"


class PlayerControls(QWidget):
    play_toggled = Signal()
    seek_request = Signal(int)        # ms
    volume_changed = Signal(float)    # 0..1
    mute_toggled = Signal()
    speed_changed = Signal(float)
    frame_step = Signal(int)          # -1 / +1
    snapshot_request = Signal()
    fullscreen_toggled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("PlayerControls")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(36)
        self.play_btn.clicked.connect(self.play_toggled.emit)
        layout.addWidget(self.play_btn)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(110)
        layout.addWidget(self.time_label)

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.valueChanged.connect(self.seek_request.emit)
        layout.addWidget(self.seek_slider, stretch=1)

        self.mute_btn = QPushButton("🔊")
        self.mute_btn.setFixedWidth(32)
        self.mute_btn.clicked.connect(self.mute_toggled.emit)
        layout.addWidget(self.mute_btn)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.valueChanged.connect(
            lambda v: self.volume_changed.emit(v / 100.0)
        )
        layout.addWidget(self.volume_slider)

        self.speed_combo = QComboBox()
        for label, _ in _SPEEDS:
            self.speed_combo.addItem(label)
        self.speed_combo.setCurrentText("1.0×")
        self.speed_combo.currentTextChanged.connect(self._on_speed_changed)
        layout.addWidget(self.speed_combo)

        self.frame_back_btn = QPushButton("◀")
        self.frame_back_btn.setFixedWidth(32)
        self.frame_back_btn.setToolTip("이전 프레임 (,)")
        self.frame_back_btn.clicked.connect(lambda: self.frame_step.emit(-1))
        layout.addWidget(self.frame_back_btn)

        self.frame_forward_btn = QPushButton("▶")
        self.frame_forward_btn.setFixedWidth(32)
        self.frame_forward_btn.setToolTip("다음 프레임 (.)")
        self.frame_forward_btn.clicked.connect(lambda: self.frame_step.emit(+1))
        layout.addWidget(self.frame_forward_btn)

        self.snapshot_btn = QPushButton("📸")
        self.snapshot_btn.setFixedWidth(34)
        self.snapshot_btn.setToolTip("현재 프레임 → 스크린샷 탭 (Ctrl+Shift+P)")
        self.snapshot_btn.clicked.connect(self.snapshot_request.emit)
        layout.addWidget(self.snapshot_btn)

        self.fullscreen_btn = QPushButton("⛶")
        self.fullscreen_btn.setFixedWidth(32)
        self.fullscreen_btn.setToolTip("풀스크린 (F)")
        self.fullscreen_btn.clicked.connect(self.fullscreen_toggled.emit)
        layout.addWidget(self.fullscreen_btn)

        self._duration_ms = 0
        self._position_ms = 0
        self._refresh_time_label()

    # ---------- 외부 API ----------
    def set_duration_ms(self, ms: int) -> None:
        self._duration_ms = max(0, ms)
        self.seek_slider.blockSignals(True)
        self.seek_slider.setRange(0, self._duration_ms)
        self.seek_slider.blockSignals(False)
        self._refresh_time_label()

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, ms)
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(self._position_ms)
        self.seek_slider.blockSignals(False)
        self._refresh_time_label()

    def set_playing(self, playing: bool) -> None:
        self.play_btn.setText("⏸" if playing else "▶")

    def set_audio_enabled(self, enabled: bool) -> None:
        self.volume_slider.setEnabled(enabled)
        self.mute_btn.setEnabled(enabled)

    def set_muted(self, muted: bool) -> None:
        self.mute_btn.setText("🔇" if muted else "🔊")

    def set_speed(self, rate: float) -> None:
        for label, val in _SPEEDS:
            if abs(val - rate) < 1e-3:
                self.speed_combo.setCurrentText(label)
                return

    # ---------- 내부 ----------
    def _on_speed_changed(self, label: str) -> None:
        for lbl, v in _SPEEDS:
            if lbl == label:
                self.speed_changed.emit(v)
                return

    def _refresh_time_label(self) -> None:
        self.time_label.setText(
            f"{_format_ms(self._position_ms)} / {_format_ms(self._duration_ms)}"
        )
