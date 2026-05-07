"""영상 탭 — PlayerWidget + PlayerControls + 곰/팟식 단축키."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QTimer, Signal
from PySide6.QtGui import QCursor, QImage, QKeyEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from ..core.settings import PlayerHotkeys, PlayerSettings
from .video.player_widget import PlayerWidget
from .video.player_controls import PlayerControls


# 풀스크린 컨트롤 오버레이 동작 상수
_FS_HIDE_DELAY_MS = 1000          # 재생 중 마우스 idle 시 숨김 지연
_FS_BOTTOM_BAND_PX = 120          # 하단에서 이 높이 안에 마우스가 들어오면 다시 표시


def _format_ms_label(ms: int) -> str:
    s = max(0, ms // 1000)
    cs = (ms % 1000) // 100
    return f"{s // 60:02d}:{s % 60:02d}.{cs}"


class VideoTab(QWidget):
    """단일 영상 탭. 메인 창에 들어갈 때만 단축키가 동작."""

    snapshot_requested = Signal(QImage, str)   # (이미지, 원본@시각 라벨)
    duration_resolved = Signal(int)            # ms — 영상 로드 후 실제 길이 확정
    trim_requested = Signal(object, int, int)  # (Path src, int in_ms, int out_ms)
    edit_mode_toggled = Signal(bool)           # 편집 모드 ON/OFF
    effect_selected = Signal(object)           # Effect | None — MainWindow 인스펙터 패널용

    def __init__(self, *, path: Path, source_label: str, duration_ms: int,
                 player_settings: PlayerSettings,
                 thumbnail: QImage | None = None,
                 player_hotkeys: PlayerHotkeys | None = None,
                 sidecar_dir: Path | None = None) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        self._source_label = source_label
        self._source_path = Path(path)
        self._settings = player_settings
        # 영상 플레이어 키 — main_window 가 settings 의 인스턴스를 그대로 넘김.
        # 사용자가 환경설정에서 키를 바꾸면 같은 인스턴스가 자동으로 반영.
        self._player_hotkeys = player_hotkeys or PlayerHotkeys()

        # 프레임 스킵 누적 — D/F 키와 ◀/▶ 버튼으로 프레임 단위 이동할 때마다 누적,
        # 다른 종류의 시크(슬라이더 드래그, 화살표 초단위 이동, Home/End) 가 일어나면 0 으로 리셋.
        # delta_ms 는 실제 player.position_ms 차이의 누적이라 단순히 N * 1/fps 가 아닌
        # 실제 영상 fps 와 정합하는 값.
        self._frame_step_accum: int = 0
        self._frame_step_accum_ms: int = 0

        # 풀스크린 오버레이 상태 — 진입 전엔 None, 진입 시 holder 위젯 + 타이머 세팅.
        # eventFilter 가 풀스크린이 아닐 때도 호출되므로 반드시 __init__ 에서 정의.
        self._fullscreen_holder: QWidget | None = None
        self._fs_hide_timer: QTimer | None = None

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

        # ---- 편집 모드 통합 (Stage 2) ----
        from .video.edit_controller import EditController
        from .video.effect_lanes_widget import EffectLanesWidget
        from ..effects import default_sidecar_dir

        sc_dir = Path(sidecar_dir) if sidecar_dir is not None else default_sidecar_dir()
        self._edit_controller = EditController(self._source_path, sc_dir)
        self._edit_controller.sidecar_replaced.connect(self._on_sidecar_replaced)
        self._edit_controller.edit_mode_toggled.connect(self.edit_mode_toggled.emit)

        self._lanes_widget = EffectLanesWidget()
        self._lanes_widget.set_sidecar(self._edit_controller.sidecar())
        if duration_ms > 0:
            self._lanes_widget.set_duration_ms(duration_ms)
        self._lanes_widget.hide()
        layout.addWidget(self._lanes_widget)

        # Task 7: PlayerControls 편집 토글 과 EditController 연결
        self.controls.edit_mode_change_requested.connect(self._edit_controller.set_edit_mode)
        self._edit_controller.edit_mode_toggled.connect(self.controls.set_edit_mode_button)
        self._edit_controller.edit_mode_toggled.connect(self._lanes_widget.setVisible)

        # lanes → VideoTab effect_selected 버블 (MainWindow 인스펙터 패널용)
        self._lanes_widget.effect_selected.connect(self.effect_selected.emit)

        # 재생 위치/지속시간 → lanes 에 전파
        self.player.position_changed.connect(self._lanes_widget.set_position_ms)
        self.player.duration_changed.connect(self._lanes_widget.set_duration_ms)

    # ---------- API ----------
    def source_label(self) -> str:
        return self._source_label

    # ---------- 편집 모드 API ----------
    def is_edit_mode_on(self) -> bool:
        return self._edit_controller.is_edit_mode_on()

    def set_edit_mode(self, on: bool) -> None:
        self._edit_controller.set_edit_mode(on)
        self._lanes_widget.setVisible(on)

    def sidecar(self):
        return self._edit_controller.sidecar()

    def lanes_widget(self):
        return self._lanes_widget

    def edit_controller(self):
        return self._edit_controller

    def _on_sidecar_replaced(self, sc) -> None:
        """controller 가 사이드카를 갱신 (undo/redo 또는 effect 변경)."""
        self._lanes_widget.set_sidecar(sc)

    # ---------- 단축키 ----------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        k = event.key()
        m = event.modifiers()
        # Ctrl+E — 편집 모드 토글
        if k == Qt.Key_E and (m & Qt.ControlModifier):
            self.set_edit_mode(not self.is_edit_mode_on())
            event.accept(); return
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
        # 프레임 단위 이동 — PlayerHotkeys 에서 동적으로 가져옴.
        # KStudio 기본: D=이전 / F=다음. 곰플 호환: A=이전 / D=다음.
        if self._matches_player_key(event, self._player_hotkeys.frame_forward):
            self._do_frame_step(+1)
            event.accept(); return
        if self._matches_player_key(event, self._player_hotkeys.frame_back):
            self._do_frame_step(-1)
            event.accept(); return
        # G = 누적 프레임 스킵 카운터 수동 초기화 (현재 위치는 유지).
        if k == Qt.Key_G:
            had_accum = self._frame_step_accum != 0 or self._frame_step_accum_ms != 0
            self._reset_frame_step_accum()
            self.player.flash_action(
                "↺ 누적 프레임 스킵 0 으로 초기화" if had_accum
                else "↺ 누적 프레임 스킵 (이미 0)"
            )
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
        if (k in (Qt.Key_Return, Qt.Key_Enter)) and (m & Qt.ControlModifier):
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

    def _matches_player_key(self, event: QKeyEvent, hotkey_str: str) -> bool:
        """이벤트가 settings 의 단일 글자 단축키와 일치하는지. modifier 없는 단일 키 한정."""
        if not hotkey_str or len(hotkey_str) != 1:
            return False
        # modifier 가 있으면 단일 글자 키와 매칭 안 함 (Ctrl+D 가 D 와 매칭되지 않도록).
        if event.modifiers() not in (Qt.NoModifier, Qt.KeypadModifier):
            return False
        text = event.text()
        if not text:
            return False
        return text.upper() == hotkey_str.upper()

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
        """슬라이더 드래그/클릭 또는 트림 레인 시크 — 누적 카운터 초기화.

        트림 모드(in/out 둘 중 하나라도 마크된 상태)에서 시크하면 자동 일시정지.
        편집 작업 중에는 사용자가 정확한 프레임을 보면서 점을 찍어야 하므로
        영상이 그대로 재생되며 다음 프레임으로 흘러가면 안 됨 (Premiere 등 표준).
        """
        trim_active = (self.controls.in_ms() is not None
                       or self.controls.out_ms() is not None)
        if trim_active and self.player.is_playing():
            self.player.pause()
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
        """PlayerControls / Ctrl+Enter 가 트림 요청 → MainWindow 로 bubble."""
        self.trim_requested.emit(self._source_path, int(in_ms), int(out_ms))

    def _on_snapshot(self) -> None:
        img = self.player.current_frame()
        if img.isNull():
            return
        ts = _format_ms_label(self.player.position_ms())
        label = f"{self._source_label} @ {ts}"
        self.snapshot_requested.emit(img, label)

    def _on_fullscreen_toggled(self) -> None:
        """플레이어 위젯을 단독으로 풀스크린에 띄움. Esc 로 복귀.

        풀스크린에서도 PlayerControls(재생/시크/볼륨 등) 를 유지해야 사용자가 영상을
        조작할 수 있다. 컨트롤바는 holder 의 자식 오버레이로 띄우고, 재생 중에는
        1초간 마우스 움직임이 없으면 자동으로 숨고, 마우스가 화면 하단 영역에 진입
        하면 다시 나타나는 표준 동작 (YouTube/VLC 와 동일).
        """
        # 이미 분리된 풀스크린 창이 있으면 닫기 (토글)
        if self._fullscreen_holder is not None:
            self._fullscreen_holder.close()
            return

        # 복귀 시 layout 의 원래 순서를 보존하기 위해 인덱스를 *modify 전* 에 캡처.
        # 한쪽을 reparent 한 뒤 indexOf 를 부르면 이미 줄어든 인덱스가 나와 복귀 시
        # 순서가 뒤집힘 (player 가 controls 뒤로 들어감 → 컨트롤바가 화면 상단에 나옴).
        player_index = self.layout().indexOf(self.player)
        ctrl_index = self.layout().indexOf(self.controls)

        # 새 top-level 창에 player 를 일시적으로 reparent.
        # holder 자체엔 layout 을 두지 않는다 — player 는 fillRect 로 깔고, controls
        # 는 raise_() 한 floating overlay 로 관리한다. 마우스 트래킹은 위젯별
        # setMouseTracking 대신 QApplication 글로벌 eventFilter 로 처리 (아래).
        holder = QWidget()
        holder.setWindowTitle("KStudio - 풀스크린")
        holder.setStyleSheet("background-color: black;")

        # player 를 holder 로 옮김 (원래 layout 에서 자동 분리)
        self.player.setParent(holder)
        self.player.show()
        self.player.setGeometry(0, 0, 1, 1)  # showFullScreen 후 resizeEvent 에서 정확히 잡음

        # controls 도 holder 의 자식으로 reparent — layout 이 아닌 floating overlay
        # 로 두어야 player 위에 겹쳐 그릴 수 있다.
        self.layout().removeWidget(self.controls)
        self.controls.setParent(holder)
        self.controls.show()

        # 자동 숨김 타이머
        hide_timer = QTimer(holder)
        hide_timer.setSingleShot(True)
        hide_timer.setInterval(_FS_HIDE_DELAY_MS)
        hide_timer.timeout.connect(lambda: self._fs_maybe_hide_controls())
        self._fs_hide_timer = hide_timer

        def _reposition_controls():
            ctrl_h = self.controls.sizeHint().height()
            self.controls.setGeometry(
                0, holder.height() - ctrl_h, holder.width(), ctrl_h,
            )
            self.controls.raise_()

        def _on_resize(ev):
            self.player.setGeometry(0, 0, holder.width(), holder.height())
            _reposition_controls()
        holder.resizeEvent = _on_resize  # type: ignore[assignment]

        # 마우스 위치 추적 — _VideoSurface 까지 mouseTracking 을 전파하고 후크하는
        # 것은 깨지기 쉽다 (페인트만 하던 위젯에 입력 이벤트 흐름이 추가됨). 대신
        # QApplication 에 eventFilter 를 달아 mouseMove 이벤트를 한 곳에서 처리.
        # 풀스크린 진입 → 등록, 종료 → 해제하는 lifecycle 이라 비용도 작다.
        QApplication.instance().installEventFilter(self)

        def _restore():
            # player + controls 를 원래 자리에 복귀. 멱등 — 한 번만 실행되도록 가드.
            if self._fullscreen_holder is None:
                return
            self._fullscreen_holder = None
            self._fs_hide_timer = None
            try:
                QApplication.instance().removeEventFilter(self)
            except (AttributeError, RuntimeError):
                pass
            try:
                self.player.setParent(None)
                self.controls.setParent(None)
            except RuntimeError:
                pass
            # 진입 전과 동일한 순서로 복귀 (player_index, ctrl_index 는 모두 modify
            # 전에 잡아둔 값). 보통 player_index=0, ctrl_index=1.
            self.layout().insertWidget(player_index, self.player, stretch=1)
            self.layout().insertWidget(ctrl_index, self.controls)
            self.player.show()
            self.controls.show()
            self.player.setFocus()

        # 닫힐 때(Esc 등) 복귀 처리
        original_keyPressEvent = holder.keyPressEvent
        def _key(ev):
            if ev.key() == Qt.Key_Escape:
                holder.close()
                return
            # F = 다음 프레임, Space = 재생/일시정지 — 풀스크린에서도 단축키 유지
            # 위해 video_tab 의 keyPressEvent 로 위임.
            self.keyPressEvent(ev)
            if not ev.isAccepted():
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
        # 진입 직후엔 컨트롤 보임 → 1초 후 (재생 중이면) 숨김 시작
        _reposition_controls()
        if self.player.is_playing():
            hide_timer.start()

    # ---------- 풀스크린 컨트롤 오버레이 ----------
    def eventFilter(self, obj, ev) -> bool:  # type: ignore[override]
        """QApplication 전역 필터 — 풀스크린 동안만 활성. 마우스가 holder 내부에서
        움직일 때 컨트롤 표시/숨김을 결정한다. 다른 이벤트는 모두 그대로 통과.
        """
        if (self._fullscreen_holder is not None
                and ev.type() == QEvent.MouseMove):
            self._fs_handle_global_mouse_move()
        return super().eventFilter(obj, ev)

    def _fs_handle_global_mouse_move(self) -> None:
        holder = self._fullscreen_holder
        if holder is None:
            return
        # 글로벌 커서 → holder 로컬 좌표 변환. 다른 모니터/창 위로 마우스가 가도
        # 안전하게 무시.
        pos = holder.mapFromGlobal(QCursor.pos())
        if not (0 <= pos.x() < holder.width() and 0 <= pos.y() < holder.height()):
            return
        in_bottom_band = pos.y() >= holder.height() - _FS_BOTTOM_BAND_PX
        if in_bottom_band:
            self.controls.show()
            self.controls.raise_()
            if self._fs_hide_timer is not None:
                self._fs_hide_timer.stop()
        else:
            # 하단 밖 — 재생 중이면 1초 후 숨김. 일시정지 상태면 그대로 둠.
            if self.player.is_playing() and self._fs_hide_timer is not None:
                self._fs_hide_timer.start()

    def _fs_maybe_hide_controls(self) -> None:
        if self._fullscreen_holder is None:
            return
        if not self.player.is_playing():
            return  # 일시정지 중엔 숨기지 않음
        self.controls.hide()
