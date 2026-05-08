"""곰/팟플레이어 스타일 영상 컨트롤 바 — 슬라이더·트림은 VideoTimeline 으로 이동.

남는 책임: ▶ play / 시간 라벨 / 음소거·볼륨 / 배속 / 프레임 step / 스냅샷 / 풀스크린 / 편집 토글.
시크 슬라이더와 트림 마커는 VideoTimeline (timeline.py) 으로 이동했다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QPushButton, QSlider, QWidget,
)

from .edit_mode_toggle import EditModeToggle
from ..icons import load_icon
from ...core.i18n import tr


_ICON_PX = 18

_SPEEDS = [("0.5×", 0.5), ("1.0×", 1.0), ("1.5×", 1.5), ("2.0×", 2.0)]
_CUSTOM_SPEED_LABEL = "사용자 지정…"


def _format_ms(ms: int) -> str:
    s = max(0, ms // 1000)
    return f"{s // 60:02d}:{s % 60:02d}"


class PlayerControls(QWidget):
    play_toggled = Signal()
    volume_changed = Signal(float)    # 0..1
    mute_toggled = Signal()
    speed_changed = Signal(float)
    frame_step = Signal(int)          # -1 / +1
    snapshot_request = Signal()
    fullscreen_toggled = Signal()
    edit_mode_change_requested = Signal(bool)   # 사용자가 편집 토글 클릭

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("PlayerControls")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.play_btn = QPushButton()
        self.play_btn.setFixedSize(36, 32)
        self.play_btn.setIcon(load_icon("play", size=_ICON_PX))
        self.play_btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
        self.play_btn.setToolTip(tr("재생/일시정지 (Space)"))
        self.play_btn.clicked.connect(self.play_toggled.emit)
        layout.addWidget(self.play_btn)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(110)
        layout.addWidget(self.time_label)

        layout.addStretch(1)

        self.mute_btn = QPushButton()
        self.mute_btn.setFixedSize(40, 32)
        self.mute_btn.setIcon(load_icon("volume-2", size=_ICON_PX))
        self.mute_btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
        self.mute_btn.setToolTip(tr("음소거 (M)"))
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
        self.speed_combo.addItem(_CUSTOM_SPEED_LABEL)
        self.speed_combo.setCurrentText("1.0×")
        self.speed_combo.currentTextChanged.connect(self._on_speed_changed)
        layout.addWidget(self.speed_combo)

        self.frame_back_btn = QPushButton()
        self.frame_back_btn.setFixedSize(40, 32)
        self.frame_back_btn.setIcon(load_icon("chevron-left", size=_ICON_PX))
        self.frame_back_btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
        self.frame_back_btn.setToolTip(tr("이전 프레임 (D)"))
        self.frame_back_btn.clicked.connect(lambda: self.frame_step.emit(-1))
        layout.addWidget(self.frame_back_btn)

        self.frame_forward_btn = QPushButton()
        self.frame_forward_btn.setFixedSize(40, 32)
        self.frame_forward_btn.setIcon(load_icon("chevron-right", size=_ICON_PX))
        self.frame_forward_btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
        self.frame_forward_btn.setToolTip(tr("다음 프레임 (F)"))
        self.frame_forward_btn.clicked.connect(lambda: self.frame_step.emit(+1))
        layout.addWidget(self.frame_forward_btn)

        self.snapshot_btn = QPushButton()
        self.snapshot_btn.setFixedSize(40, 32)
        self.snapshot_btn.setIcon(load_icon("camera", size=_ICON_PX))
        self.snapshot_btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
        self.snapshot_btn.setToolTip(tr("현재 프레임 → 스크린샷 탭 (Ctrl+Shift+P)"))
        self.snapshot_btn.clicked.connect(self.snapshot_request.emit)
        layout.addWidget(self.snapshot_btn)

        self.fullscreen_btn = QPushButton()
        self.fullscreen_btn.setFixedSize(40, 32)
        self.fullscreen_btn.setIcon(load_icon("maximize", size=_ICON_PX))
        self.fullscreen_btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
        self.fullscreen_btn.setToolTip(tr("풀스크린"))
        self.fullscreen_btn.clicked.connect(self.fullscreen_toggled.emit)
        layout.addWidget(self.fullscreen_btn)

        self.edit_toggle = EditModeToggle()
        self.edit_toggle.toggled_changed.connect(self.edit_mode_change_requested.emit)
        layout.addWidget(self.edit_toggle)

        self._duration_ms = 0
        self._position_ms = 0
        self._refresh_time_label()

    # ---------- 외부 API ----------
    def set_duration_ms(self, ms: int) -> None:
        self._duration_ms = max(0, ms)
        self._refresh_time_label()

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, ms)
        self._refresh_time_label()

    def set_playing(self, playing: bool) -> None:
        name = "pause" if playing else "play"
        self.play_btn.setIcon(load_icon(name, size=_ICON_PX))

    def set_audio_enabled(self, enabled: bool) -> None:
        self.volume_slider.setEnabled(enabled)
        self.mute_btn.setEnabled(enabled)

    def set_muted(self, muted: bool) -> None:
        name = "volume-x" if muted else "volume-2"
        self.mute_btn.setIcon(load_icon(name, size=_ICON_PX))

    def set_speed(self, rate: float) -> None:
        for label, val in _SPEEDS:
            if abs(val - rate) < 1e-3:
                self.speed_combo.setCurrentText(label)
                return
        custom = f"{rate:.2f}×"
        idx_custom = self.speed_combo.findText(_CUSTOM_SPEED_LABEL)
        existing = self.speed_combo.findText(custom)
        if existing >= 0:
            self.speed_combo.setCurrentIndex(existing)
        else:
            insert_at = idx_custom if idx_custom >= 0 else self.speed_combo.count()
            self.speed_combo.insertItem(insert_at, custom)
            self.speed_combo.setCurrentText(custom)

    def set_edit_mode_button(self, on: bool) -> None:
        self.edit_toggle.set_on(on)

    # ---------- 내부 ----------
    def _on_speed_changed(self, label: str) -> None:
        if label == _CUSTOM_SPEED_LABEL:
            value, ok = QInputDialog.getDouble(
                self, "재생 속도 지정", "배수:", 1.0, 0.1, 16.0, 2,
            )
            if not ok:
                self.speed_combo.blockSignals(True)
                self.speed_combo.setCurrentText("1.0×")
                self.speed_combo.blockSignals(False)
                self.speed_changed.emit(1.0)
                return
            self.set_speed(value)
            self.speed_changed.emit(value)
            return
        for lbl, v in _SPEEDS:
            if lbl == label:
                self.speed_changed.emit(v)
                return
        try:
            v = float(label.replace("×", "").strip())
            self.speed_changed.emit(v)
        except ValueError:
            pass

    def _refresh_time_label(self) -> None:
        self.time_label.setText(
            f"{_format_ms(self._position_ms)} / {_format_ms(self._duration_ms)}"
        )
