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
    trim_requested = Signal(object, int, int)  # (Path src, int in_ms, int out_ms)

    def __init__(self, *, path: Path, source_label: str, duration_ms: int,
                 player_settings: PlayerSettings,
                 thumbnail: QImage | None = None) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        self._source_label = source_label
        self._source_path = Path(path)
        self._settings = player_settings

        # 프레임 스킵 누적 — D/F 키와 ◀/▶ 버튼으로 프레임 단위 이동할 때마다 누적,
        # 다른 종류의 시크(슬라이더 드래그, 화살표 초단위 이동, Home/End) 가 일어나면 0 으로 리셋.
        # delta_ms 는 실제 player.position_ms 차이의 누적이라 단순히 N * 1/fps 가 아닌
        # 실제 영상 fps 와 정합하는 값.
        self._frame_step_accum: int = 0
        self._frame_step_accum_ms: int = 0

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
        # 재생 토글(스페이스 / 컨트롤바 ▶ 클릭) 도 시점이 바뀌니 누적 프레임 스킵 리셋.
        self.controls.play_toggled.connect(self._on_user_play_toggle)
        # 사용자가 슬라이더를 드래그/클릭하면 누적 프레임 스킵 카운터 리셋. 프로그래매틱
        # set_position_ms 는 controls 쪽에서 blockSignals 처리되므로 여기로 들어오지 않음.
        self.controls.seek_request.connect(self._on_user_seek_request)
        self.controls.volume_changed.connect(self.player.set_volume)
        self.controls.mute_toggled.connect(self._toggle_mute)
        self.controls.speed_changed.connect(self.player.set_playback_rate)
        self.controls.frame_step.connect(self._on_frame_step_button)
        self.controls.snapshot_request.connect(self._on_snapshot)
        self.controls.fullscreen_toggled.connect(self._on_fullscreen_toggled)
        # 트림 시그널 — PlayerControls → MainWindow 로 bubble
        self.controls.trim_execute_requested.connect(self._on_trim_execute)

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
            self._reset_frame_step_accum()
            event.accept(); return
        if k == Qt.Key_Right:
            delta = self._delta_for_modifier(m, sign=+1)
            self.player.seek_seconds(delta)
            self.player.flash_action(f"▶▶ +{abs(delta):g}초")
            self._reset_frame_step_accum()
            event.accept(); return
        if k == Qt.Key_Left:
            delta = self._delta_for_modifier(m, sign=-1)
            self.player.seek_seconds(delta)
            self.player.flash_action(f"◀◀ -{abs(delta):g}초")
            self._reset_frame_step_accum()
            event.accept(); return
        # 프레임 단위 이동: D = 이전 프레임, F = 다음 프레임 (사용자 요청 단축키).
        if k == Qt.Key_F:
            self._do_frame_step(+1)
            event.accept(); return
        if k == Qt.Key_D:
            self._do_frame_step(-1)
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
            self._reset_frame_step_accum()
            event.accept(); return
        if k == Qt.Key_End:
            self.player.seek_ms(self.player.duration_ms())
            self.player.flash_action("⏭ 끝으로")
            self._reset_frame_step_accum()
            event.accept(); return
        # ===== 트림 단축키 =====
        if k == Qt.Key_BracketLeft:
            self.controls.set_in_ms(self.player.position_ms())
            self.player.flash_action("[ 시작점")
            event.accept(); return
        if k == Qt.Key_BracketRight:
            self.controls.set_out_ms(self.player.position_ms())
            self.player.flash_action("] 끝점")
            event.accept(); return
        if k == Qt.Key_E and (m & Qt.ControlModifier):
            if self.controls.cut_btn.isEnabled():
                self._on_trim_execute(
                    self.controls.in_ms() or 0,
                    self.controls.out_ms() or 0,
                )
            event.accept(); return
        if k == Qt.Key_Escape:
            had = self.controls.in_ms() is not None or self.controls.out_ms() is not None
            if had:
                self.controls.clear_trim()
                self.player.flash_action("✕ 트림 해제")
                event.accept(); return
        super().keyPressEvent(event)

    def _on_frame_step_button(self, direction: int) -> None:
        """컨트롤바의 ◀/▶ 프레임 버튼 → 단축키와 동일하게 프레임 step + 누적 HUD."""
        self._do_frame_step(direction)

    def _do_frame_step(self, direction: int) -> None:
        """프레임 단위 이동 + 누적 카운터 갱신 + HUD 표시 (D/F 키 / ◀▶ 버튼 공통)."""
        before_ms = self.player.position_ms()
        self.player.step_frame(direction)
        after_ms = self.player.position_ms()
        delta_ms = after_ms - before_ms
        self._frame_step_accum += direction
        self._frame_step_accum_ms += delta_ms
        # HUD: 단발 표시 + 누적 (스킵 횟수 + 시간). 부호는 +N / -N 로 직관적으로 보이게.
        single = "+1 프레임" if direction > 0 else "-1 프레임"
        arrow = "▶" if direction > 0 else "◀"
        accum_n = self._frame_step_accum
        accum_sign = "+" if accum_n >= 0 else ""
        sec = self._frame_step_accum_ms / 1000.0
        sec_str = f"{sec:+.2f}초"
        self.player.flash_action(
            f"{arrow} {single} (누적 프레임 스킵 {accum_sign}{accum_n}, {sec_str})"
        )

    def _reset_frame_step_accum(self) -> None:
        self._frame_step_accum = 0
        self._frame_step_accum_ms = 0

    def _on_user_seek_request(self, ms: int) -> None:
        """슬라이더 드래그/클릭으로 사용자가 시크 — 누적 카운터 초기화."""
        self.player.seek_ms(ms)
        self._reset_frame_step_accum()

    def _on_user_play_toggle(self) -> None:
        """재생 토글 (스페이스 / 컨트롤바 ▶ 버튼) — 누적 카운터 초기화."""
        self.player.toggle_play()
        self._reset_frame_step_accum()

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

    def _on_trim_execute(self, in_ms: int, out_ms: int) -> None:
        """PlayerControls / Ctrl+E 가 트림 요청 → MainWindow 로 bubble."""
        self.trim_requested.emit(self._source_path, int(in_ms), int(out_ms))

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
