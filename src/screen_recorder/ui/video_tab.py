"""영상 탭 — PlayerWidget + PlayerControls + 곰/팟식 단축키."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QKeyEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..core.settings import PlayerSettings
from .video.player_widget import PlayerWidget
from .video.player_controls import PlayerControls


def _format_ms_label(ms: int) -> str:
    s = max(0, ms // 1000)
    cs = (ms % 1000) // 100
    return f"{s // 60:02d}:{s % 60:02d}.{cs}"


class VideoTab(QWidget):
    """단일 영상 탭. 메인 창에 들어갈 때만 단축키가 동작."""

    snapshot_requested = Signal(QImage, str)   # (이미지, 원본@시각 라벨)

    def __init__(self, *, path: Path, source_label: str, duration_ms: int,
                 player_settings: PlayerSettings) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        self._source_label = source_label
        self._settings = player_settings

        self.player = PlayerWidget()
        self.controls = PlayerControls()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.player, stretch=1)
        layout.addWidget(self.controls)

        # 모델 → 컨트롤
        self.player.position_changed.connect(self.controls.set_position_ms)
        self.player.duration_changed.connect(self.controls.set_duration_ms)
        self.player.playing_changed.connect(self.controls.set_playing)

        # 컨트롤 → 모델
        self.controls.play_toggled.connect(self.player.toggle_play)
        self.controls.seek_request.connect(self.player.seek_ms)
        self.controls.volume_changed.connect(self.player.set_volume)
        self.controls.mute_toggled.connect(self._toggle_mute)
        self.controls.speed_changed.connect(self.player.set_playback_rate)
        self.controls.frame_step.connect(self.player.step_frame)
        self.controls.snapshot_request.connect(self._on_snapshot)
        # 풀스크린은 메인 창에서 처리하므로 시그널만 외부로 노출 (현재는 보류)

        self.player.load(path)
        self.controls.set_audio_enabled(self.player.has_audio())
        if duration_ms > 0:
            self.controls.set_duration_ms(duration_ms)

    # ---------- API ----------
    def source_label(self) -> str:
        return self._source_label

    # ---------- 단축키 ----------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        k = event.key()
        m = event.modifiers()
        if k == Qt.Key_Space:
            self.player.toggle_play()
            event.accept(); return
        if k == Qt.Key_Right:
            delta = self._delta_for_modifier(m, sign=+1)
            self.player.seek_seconds(delta)
            event.accept(); return
        if k == Qt.Key_Left:
            delta = self._delta_for_modifier(m, sign=-1)
            self.player.seek_seconds(delta)
            event.accept(); return
        if k == Qt.Key_Period:
            self.player.step_frame(+1); event.accept(); return
        if k == Qt.Key_Comma:
            self.player.step_frame(-1); event.accept(); return
        if k == Qt.Key_Up:
            self._bump_volume(+0.1); event.accept(); return
        if k == Qt.Key_Down:
            self._bump_volume(-0.1); event.accept(); return
        if k == Qt.Key_M:
            self._toggle_mute(); event.accept(); return
        if k == Qt.Key_Less:
            self._bump_speed(-1); event.accept(); return
        if k == Qt.Key_Greater:
            self._bump_speed(+1); event.accept(); return
        if k == Qt.Key_Home:
            self.player.seek_ms(0); event.accept(); return
        if k == Qt.Key_End:
            self.player.seek_ms(self.player.duration_ms()); event.accept(); return
        super().keyPressEvent(event)

    def _delta_for_modifier(self, m: Qt.KeyboardModifier, sign: int) -> float:
        if m & Qt.ControlModifier:
            return sign * self._settings.skip_large_seconds
        if m & Qt.ShiftModifier:
            return sign * self._settings.skip_medium_seconds
        return sign * self._settings.skip_seconds

    def _bump_volume(self, delta: float) -> None:
        cur = self.controls.volume_slider.value() / 100.0
        new = max(0.0, min(1.0, cur + delta))
        self.controls.volume_slider.setValue(int(new * 100))

    def _toggle_mute(self) -> None:
        new_muted = not self.player.is_muted()
        self.player.set_muted(new_muted)
        self.controls.set_muted(new_muted)

    def _bump_speed(self, direction: int) -> None:
        cur = self.controls.speed_combo.currentIndex()
        target = max(0, min(self.controls.speed_combo.count() - 1, cur + direction))
        self.controls.speed_combo.setCurrentIndex(target)

    def _on_snapshot(self) -> None:
        img = self.player.current_frame()
        if img.isNull():
            return
        ts = _format_ms_label(self.player.position_ms())
        label = f"{self._source_label} @ {ts}"
        self.snapshot_requested.emit(img, label)
