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
    duration_resolved = Signal(int)            # ms — 영상 로드 후 실제 길이 확정

    def __init__(self, *, path: Path, source_label: str, duration_ms: int,
                 player_settings: PlayerSettings,
                 thumbnail: QImage | None = None) -> None:
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
        self.player.duration_changed.connect(self.duration_resolved.emit)
        self.player.playing_changed.connect(self.controls.set_playing)

        # 컨트롤 → 모델
        self.controls.play_toggled.connect(self.player.toggle_play)
        self.controls.seek_request.connect(self.player.seek_ms)
        self.controls.volume_changed.connect(self.player.set_volume)
        self.controls.mute_toggled.connect(self._toggle_mute)
        self.controls.speed_changed.connect(self.player.set_playback_rate)
        self.controls.frame_step.connect(self._on_frame_step_button)
        self.controls.snapshot_request.connect(self._on_snapshot)
        self.controls.fullscreen_toggled.connect(self._on_fullscreen_toggled)

        self.player.load(path)
        if thumbnail is not None and not thumbnail.isNull():
            self.player.set_thumbnail(thumbnail)
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
            self.player.flash_action(f"▶▶ +{abs(delta):g}초")
            event.accept(); return
        if k == Qt.Key_Left:
            delta = self._delta_for_modifier(m, sign=-1)
            self.player.seek_seconds(delta)
            self.player.flash_action(f"◀◀ -{abs(delta):g}초")
            event.accept(); return
        if k == Qt.Key_Period:
            self.player.step_frame(+1)
            self.player.flash_action("▶ +1 프레임")
            event.accept(); return
        if k == Qt.Key_Comma:
            self.player.step_frame(-1)
            self.player.flash_action("◀ -1 프레임")
            event.accept(); return
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
            self.player.seek_ms(0)
            self.player.flash_action("⏮ 처음으로")
            event.accept(); return
        if k == Qt.Key_End:
            self.player.seek_ms(self.player.duration_ms())
            self.player.flash_action("⏭ 끝으로")
            event.accept(); return
        super().keyPressEvent(event)

    def _on_frame_step_button(self, direction: int) -> None:
        """컨트롤바의 ◀/▶ 프레임 버튼 → 플레이어 step + HUD 표시."""
        self.player.step_frame(direction)
        if direction > 0:
            self.player.flash_action("▶ +1 프레임")
        else:
            self.player.flash_action("◀ -1 프레임")

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

    def _on_fullscreen_toggled(self) -> None:
        """플레이어 위젯을 단독으로 풀스크린에 띄움. Esc 로 복귀."""
        # 이미 분리된 풀스크린 창이 있으면 닫기 (토글)
        existing = getattr(self, "_fullscreen_holder", None)
        if existing is not None:
            existing.close()
            return

        # 새 top-level 창에 player 를 일시적으로 reparent
        from PySide6.QtCore import Qt
        holder = QWidget()
        holder.setWindowTitle("KStudio - 풀스크린")
        holder.setStyleSheet("background-color: black;")
        h_layout = QVBoxLayout(holder)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(0)
        # player 를 holder 로 옮김 (원래 layout 에서 자동 분리)
        self.player.setParent(holder)
        h_layout.addWidget(self.player)

        def _restore():
            # player 를 원래 자리에 복귀. 멱등 — 한 번만 실행되도록 가드.
            if self._fullscreen_holder is None:
                return
            self._fullscreen_holder = None
            try:
                holder.layout().removeWidget(self.player)
            except (RuntimeError, AttributeError):
                pass
            self.layout().insertWidget(0, self.player, stretch=1)
            self.player.show()
            self.player.setFocus()

        # 닫힐 때(Esc 등) 복귀 처리
        original_keyPressEvent = holder.keyPressEvent
        def _key(ev):
            if ev.key() == Qt.Key_Escape:
                holder.close()
                return
            original_keyPressEvent(ev)
        holder.keyPressEvent = _key   # type: ignore[assignment]

        # WA_DeleteOnClose 미적용 + 강한 참조(self._fullscreen_holder) 때문에
        # destroyed 시그널은 절대 발화하지 않는다. close 직전(closeEvent)에 복귀시켜
        # player 가 holder 의 자식 상태로 남아 사라지는 일을 방지.
        original_closeEvent = holder.closeEvent
        def _close(ev):
            _restore()
            original_closeEvent(ev)
        holder.closeEvent = _close   # type: ignore[assignment]

        holder.showFullScreen()
        self._fullscreen_holder = holder
