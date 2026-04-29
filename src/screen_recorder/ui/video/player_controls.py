"""곰/팟플레이어 스타일 영상 컨트롤 바."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QPushButton, QSlider, QWidget,
)


_SPEEDS = [("0.5×", 0.5), ("1.0×", 1.0), ("1.5×", 1.5), ("2.0×", 2.0)]
_CUSTOM_SPEED_LABEL = "사용자 지정…"


def _bump_font_size(btn: QPushButton, points: int) -> None:
    """버튼 텍스트 폰트를 키운다 (이모지 아이콘 가독성용)."""
    f = btn.font()
    f.setPointSize(points)
    btn.setFont(f)


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
        self.speed_combo.addItem(_CUSTOM_SPEED_LABEL)   # 맨 끝: 사용자 지정 입력
        self.speed_combo.setCurrentText("1.0×")
        self.speed_combo.currentTextChanged.connect(self._on_speed_changed)
        layout.addWidget(self.speed_combo)

        # 프레임 스텝/스냅샷/풀스크린 — 아이콘 가독성을 위해 크게.
        self.frame_back_btn = QPushButton("◀")
        self.frame_back_btn.setFixedSize(40, 32)
        self.frame_back_btn.setToolTip("이전 프레임 (,)")
        self.frame_back_btn.clicked.connect(lambda: self.frame_step.emit(-1))
        _bump_font_size(self.frame_back_btn, 16)
        layout.addWidget(self.frame_back_btn)

        self.frame_forward_btn = QPushButton("▶")
        self.frame_forward_btn.setFixedSize(40, 32)
        self.frame_forward_btn.setToolTip("다음 프레임 (.)")
        self.frame_forward_btn.clicked.connect(lambda: self.frame_step.emit(+1))
        _bump_font_size(self.frame_forward_btn, 16)
        layout.addWidget(self.frame_forward_btn)

        self.snapshot_btn = QPushButton("📸")
        self.snapshot_btn.setFixedSize(40, 32)
        self.snapshot_btn.setToolTip("현재 프레임 → 스크린샷 탭 (Ctrl+Shift+P)")
        self.snapshot_btn.clicked.connect(self.snapshot_request.emit)
        _bump_font_size(self.snapshot_btn, 16)
        layout.addWidget(self.snapshot_btn)

        self.fullscreen_btn = QPushButton("⛶")
        self.fullscreen_btn.setFixedSize(40, 32)
        self.fullscreen_btn.setToolTip("풀스크린 (F)")
        self.fullscreen_btn.clicked.connect(self.fullscreen_toggled.emit)
        _bump_font_size(self.fullscreen_btn, 16)
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
        # 프리셋과 매칭되면 그 라벨, 아니면 사용자 지정 라벨로 임시 추가.
        for label, val in _SPEEDS:
            if abs(val - rate) < 1e-3:
                self.speed_combo.setCurrentText(label)
                return
        custom = f"{rate:.2f}×"
        # 사용자 지정 라벨 위치(맨 끝 - 1) 에 임시 추가
        idx_custom = self.speed_combo.findText(_CUSTOM_SPEED_LABEL)
        # 기존 사용자 지정 결과 라벨이 있으면 갱신, 없으면 삽입
        existing = self.speed_combo.findText(custom)
        if existing >= 0:
            self.speed_combo.setCurrentIndex(existing)
        else:
            insert_at = idx_custom if idx_custom >= 0 else self.speed_combo.count()
            self.speed_combo.insertItem(insert_at, custom)
            self.speed_combo.setCurrentText(custom)

    # ---------- 내부 ----------
    def _on_speed_changed(self, label: str) -> None:
        if label == _CUSTOM_SPEED_LABEL:
            # 입력 다이얼로그 → 0.1~16.0 배수
            value, ok = QInputDialog.getDouble(
                self, "재생 속도 지정", "배수:", 1.0, 0.1, 16.0, 2,
            )
            if not ok:
                # 취소 시 1.0× 로 복귀
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
        # 사용자가 추가한 임시 라벨 ("1.30×" 등)
        try:
            v = float(label.replace("×", "").strip())
            self.speed_changed.emit(v)
        except ValueError:
            pass

    def _refresh_time_label(self) -> None:
        self.time_label.setText(
            f"{_format_ms(self._position_ms)} / {_format_ms(self._duration_ms)}"
        )
