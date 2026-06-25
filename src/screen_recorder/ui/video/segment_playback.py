"""SegmentPlaybackController — video_track 의 segment 를 순차 재생 + gap 지원.

기존 InsertPlaybackController (메인+보조 player) 를 대체. 트랙 모델에선 모든 segment 가
동등하므로 player 1개면 충분 — 다음 segment 로 넘어갈 때 setSource + seek 만.

Stage 1 (gap 모델):
- segment.start_ms 가 트랙상 시작 위치. 사이사이에 갭(gap) 가능.
- 결합 시간축 길이 = max(end_ms) over all segments.
- 갭 구간 재생 = 검은 화면 + 무음. 자동 스킵 안 함. 가상 시계(QTimer) 로 시간만 흐름.

책임:
- 결합 시간축 (max end_ms) 계산 + 외부에 emit
- 메인 player position → 결합 ms 변환 + segment 끝 도달 시 다음 segment / 갭 진입
- 사용자 시크 (combined_ms) → 적절한 segment / 갭 으로 switch

UI 의존을 회피하기 위해 player 는 추상 인터페이스 (PlayerWidget) 로 받음.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from ...effects import Sidecar
from ...effects.segment import VideoSegment


_GAP_TICK_MS = 33   # ~30fps. 갭 구간 가상 시계 진동 주기.


class SegmentPlaybackController(QObject):
    """단일 player + segment 순차 재생 + 갭 지원."""

    combined_position_changed = Signal(int)      # 결합 시간축 ms
    combined_duration_changed = Signal(int)
    active_segment_changed = Signal(str)         # segment id (갭이면 빈 문자열)

    def __init__(self, player) -> None:
        """player 는 PlayerWidget — load(path), seek_ms(ms), play(), pause(),
        position_ms(), duration_ms(), show_black_frame(), is_playing() 메서드 제공.
        position_changed Signal 지원."""
        super().__init__()
        self._player = player
        self._segments: list[VideoSegment] = []
        self._active_idx: int = -1   # 현재 로드된 segment 의 인덱스. 갭이면 -1.
        self._loaded_src: Optional[str] = None
        # 갓 활성화 직후 가드 — 다음 segment 로 막 넘긴 직후 도착하는 stale end 신호
        # (EndOfMedia / positionChanged)가 곧장 또 advance 하지 않도록. 첫 정상
        # in-segment position 에서 해제. 사용자 시크는 가드하지 않음.
        self._just_activated: bool = False
        # 갭 진입/이탈 상태.
        self._in_gap: bool = False
        self._gap_combined_ms: int = 0
        self._gap_was_playing: bool = False
        self._gap_timer = QTimer(self)
        self._gap_timer.setInterval(_GAP_TICK_MS)
        self._gap_timer.timeout.connect(self._on_gap_tick)
        # 갭 안에서 일시정지 → 재생 누르면 가상 시계가 다시 흘러야 함.
        # player 의 playing_changed 시그널을 받아 timer 토글.
        if hasattr(player, "playing_changed"):
            try:
                player.playing_changed.connect(self._on_player_playing_changed)
            except (AttributeError, TypeError):
                pass

    # ---------- public ----------
    def set_sidecar(self, sidecar: Sidecar) -> None:
        """사이드카 변경 시 segment 리스트 갱신 + 결합 길이 emit."""
        self._segments = list(sidecar.video_track)
        self.combined_duration_changed.emit(self.combined_duration_ms())
        if self._active_idx >= len(self._segments):
            self._active_idx = -1
            self._loaded_src = None
        # 첫 set_sidecar — VideoTab.__init__ 에서 외부 player.load(path) 가
        # 이미 첫 segment 의 src 를 로드한 상태. _loaded_src 를 None 으로 두면
        # 사용자의 첫 슬라이더 시크에서 _activate_segment 가 같은 파일을 재 load —
        # setSource 가 비동기라 직후 setPosition 이 무시돼 영상이 갱신 안 되는
        # 회귀가 생긴다. 첫 segment 의 src 와 동기화해 reload 자체를 막는다.
        if self._segments and self._active_idx < 0:
            self._active_idx = 0
            self._loaded_src = self._segments[0].src

    def combined_duration_ms(self) -> int:
        """트랙 결합 길이 = 모든 segment 의 end_ms 의 최대값. 빈 트랙이면 0."""
        return max((s.end_ms for s in self._segments), default=0)

    def seek_combined_ms(self, t_combined: int) -> None:
        """슬라이더 시크 → 해당 위치의 segment / 갭 으로 switch."""
        t = max(0, int(t_combined))
        seg, local = self._segment_at(t)
        if seg is None:
            self._enter_gap(t)
            return
        self._exit_gap()
        idx = self._segments.index(seg)
        self._activate_segment(idx, seek_local_ms=local)
        # 사용자 시크는 직후 첫 position 이 곧장 경계일 수 있어 advance 가드 안 함.
        self._just_activated = False

    def on_media_ended(self) -> None:
        """player 의 EndOfMedia(소스 파일 끝) — 현재 segment 끝으로 간주하고 진행.

        position_changed 기반 advance 는 segment 가 자기 소스 파일의 끝에서 끝날 때
        (마지막 위치 신호가 seg_dur 에 못 미치고 player 가 멈춤) 누락된다. 사용자 보고:
        4개 클립 중 3번째(소스 끝)에서 멈추고 4번째로 안 넘어감. EndOfMedia 를 두 번째
        advance 경로로 받아 다음 클립/갭으로 확실히 넘긴다.
        """
        if self._in_gap or self._active_idx < 0 or not self._segments:
            return
        if self._just_activated:
            # position 기반 advance 가 이미 다음 클립으로 넘긴 뒤 도착한 뒤늦은 신호 —
            # 재-advance 금지. EndOfMedia 는 '재생 중이었음' 을 뜻하니 재생만 보장.
            self._player.play()
            return
        self._advance_past(self._segments[self._active_idx], resume_play=True)

    def on_main_position_changed(self, ms: int) -> None:
        """player 의 position 변화 — 결합 ms 로 변환 emit + segment 끝 검사."""
        from ...core.perf_diag import inc as _perf_inc
        _perf_inc("raw_pos")
        if self._in_gap:
            # 갭 동안엔 player 가 paused — position_changed 가 와도 무시.
            return
        if self._active_idx < 0 or not self._segments:
            self.combined_position_changed.emit(int(ms))
            _perf_inc("combined_pos")
            return
        seg = self._segments[self._active_idx]
        local_ms = max(0, int(ms) - int(seg.src_in_ms))
        combined = seg.start_ms + local_ms
        self.combined_position_changed.emit(int(combined))
        _perf_inc("combined_pos")
        seg_dur = seg.duration_ms
        if seg_dur > 0 and local_ms >= seg_dur:
            self._try_advance(seg)
        else:
            # 정상 in-segment 위치 — 갓 활성화 가드 해제.
            self._just_activated = False

    # ---------- internal ----------
    def _try_advance(self, from_seg: VideoSegment) -> None:
        """현재 segment 끝 도달 → 다음으로 진행. 단, 갓 활성화된 직후의 stale 신호면
        무시(position 기반 + EndOfMedia 가 둘 다 와 중복 advance 하는 회귀 방지)."""
        if self._just_activated:
            return
        self._advance_past(from_seg)

    def _advance_past(self, seg: VideoSegment, *, resume_play: bool = False) -> None:
        """seg.end_ms 시점의 다음 트랙 위치로 진행 — 다음 segment / 갭 / 트랙 끝.

        경계가 갭/다른 segment 인지 검사. resume_play=True 면 (EndOfMedia 경로처럼
        player 가 이미 멈춰 is_playing()=False 여도) 다음에서 재생을 이어간다.
        """
        next_t = seg.end_ms
        next_seg, next_local = self._segment_at(next_t)
        if next_seg is None:
            # 마지막 segment 끝 또는 갭 진입.
            if next_t >= self.combined_duration_ms():
                self._player.pause()
                self.combined_position_changed.emit(int(next_t))
            else:
                self._enter_gap(next_t, assume_playing=resume_play)
        else:
            idx = self._segments.index(next_seg)
            self._activate_segment(idx, seek_local_ms=next_local,
                                   assume_playing=resume_play)
    def _segment_at(self, combined_ms: int) -> tuple[Optional[VideoSegment], int]:
        """결합 ms 위치의 segment 와 그 안의 local ms. 갭이면 (None, 0).

        경계 (end_ms) 는 다음 segment 의 start 로 간주 (배타적 end). 같은 시점에
        두 segment 끝/시작이 닿아 있으면 시작하는 쪽을 우선.
        """
        for s in self._segments:
            if s.start_ms <= combined_ms < s.end_ms:
                return s, combined_ms - s.start_ms
        return None, 0

    def _activate_segment(self, idx: int, *, seek_local_ms: int = 0,
                          assume_playing: bool = False) -> None:
        """segment 를 활성화 — source 가 다르면 load, 같으면 seek 만.

        assume_playing=True 면 player.is_playing() 가 False(EndOfMedia 직후 등)여도
        재생 중이었던 것으로 간주해 새 src 로드 후 재생을 이어간다.

        다음 segment 진입 시 player.load() 가 새 미디어를 비동기 로딩 — 그 직후
        play() 호출 안 하면 새 segment 가 paused 상태로 멈춤. 이전 상태 (재생 중)
        를 기억해 load 후 자동 재개. seek_ms 의 mediaStatus 확인이 비동기라 즉시
        play() 가 무시될 수 있어 mediaStatus signal 한 번 받으면 재개.
        """
        if not (0 <= idx < len(self._segments)):
            return
        prev_idx = self._active_idx   # hold_last_frame 판정용 — 갱신 전에 캡처.
        seg = self._segments[idx]
        target_src = seg.src
        target_seek_ms = int(seg.src_in_ms) + max(0, seek_local_ms)
        was_playing = bool(assume_playing
                           or getattr(self._player, "is_playing", lambda: False)())
        src_changed = (self._loaded_src != target_src)
        # _active_idx 를 load() 보다 *먼저* 갱신한다. setSource(B) 가 새 미디어
        # position 을 0 으로 리셋하며 positionChanged(0) 을 (동기/재진입) 쏘는데,
        # 그때 _active_idx 가 아직 옛 segment 면 combined = 옛.start_ms(=0) 로 환산돼
        # 재생바가 트랙 처음으로 튄다. 새 segment 를 먼저 가리키면 0 은 seg.start_ms 로
        # 환산돼 경계 위치에 머문다.
        self._active_idx = idx
        if src_changed:
            # 영상→영상 전환일 때만 직전 프레임을 유지해 경계 회색 깜빡임을 막는다.
            # 직전이 갭(-1)/이미지/GIF 면 surface 의 프레임이 stale 이거나 없으므로
            # 정상 clear 로 새 프레임을 받는다.
            prev_seg = (self._segments[prev_idx]
                        if 0 <= prev_idx < len(self._segments) else None)
            hold_last_frame = (
                seg.media_kind == "video"
                and prev_seg is not None
                and prev_seg.media_kind == "video"
            )
            self._player.load(Path(target_src), hold_last_frame=hold_last_frame)
            self._loaded_src = target_src
        self._player.seek_ms(int(target_seek_ms))
        self.active_segment_changed.emit(seg.id)
        # src 가 바뀌면 load 후 paused 상태가 됨. 이전 재생 중이었으면 재개.
        # assume_playing(EndOfMedia 경로)면 src 변화 여부와 무관하게 재생을 보장.
        if was_playing and (src_changed or assume_playing):
            self._player.play()
        # 갓 활성화 — 직후 도착하는 stale end 신호가 곧장 또 advance 하지 않도록 가드.
        self._just_activated = True

    # ---------- gap 처리 ----------
    def _enter_gap(self, combined_ms: int, *, assume_playing: bool = False) -> None:
        """갭 진입 — player pause + 검은 화면 + 가상 시계 시작(재생 중일 때만).

        assume_playing=True 면 player.is_playing()=False(EndOfMedia 직후 등)여도
        재생 중이었던 것으로 간주해 가상 시계를 돌려 다음 segment 까지 진행한다.
        """
        self._gap_combined_ms = int(combined_ms)
        was_playing = bool(assume_playing
                           or getattr(self._player, "is_playing", lambda: False)())
        self._gap_was_playing = was_playing
        if was_playing:
            self._player.pause()
        # 검은 화면 (PlayerWidget API).
        show_black = getattr(self._player, "show_black_frame", None)
        if callable(show_black):
            show_black()
        self._in_gap = True
        self._active_idx = -1
        self.active_segment_changed.emit("")
        self.combined_position_changed.emit(int(combined_ms))
        if was_playing:
            self._gap_timer.start()

    def _exit_gap(self) -> None:
        """갭 이탈 — 가상 시계 정지."""
        self._in_gap = False
        if self._gap_timer.isActive():
            self._gap_timer.stop()

    def _on_player_playing_changed(self, playing: bool) -> None:
        """갭 안에서 사용자가 일시정지/재생 토글하면 가상 시계도 따라감.

        갭 진입 시 paused 상태였다가 사용자가 ▶ 누르면 timer 가 시작돼야 다음 segment 로
        진행 가능. (없으면 player.play() 가 이전 segment 의 frozen frame 만 보여주고
        시간 진행 안 함 — advisor 발견 회귀)
        """
        if not self._in_gap:
            return
        self._gap_was_playing = bool(playing)
        if playing and not self._gap_timer.isActive():
            self._gap_timer.start()
        elif not playing and self._gap_timer.isActive():
            self._gap_timer.stop()

    def _on_gap_tick(self) -> None:
        """갭 진동 — 가상 시간 진행. segment 진입 시 활성화."""
        if not self._in_gap:
            self._gap_timer.stop()
            return
        self._gap_combined_ms += _GAP_TICK_MS
        # 트랙 끝 도달 → 정지.
        total = self.combined_duration_ms()
        if self._gap_combined_ms >= total:
            self._gap_timer.stop()
            self._in_gap = False
            self.combined_position_changed.emit(int(total))
            return
        seg, local = self._segment_at(self._gap_combined_ms)
        if seg is None:
            # 아직 갭 안.
            self.combined_position_changed.emit(int(self._gap_combined_ms))
            return
        # segment 진입 — 활성화 + 재생 재개 (갭 진입 시 재생 중이었으면).
        self._gap_timer.stop()
        self._in_gap = False
        idx = self._segments.index(seg)
        self._activate_segment(idx, seek_local_ms=local)
        if self._gap_was_playing:
            self._player.play()

    @property
    def active_segment_id(self) -> Optional[str]:
        if self._in_gap:
            return None
        if self._active_idx < 0 or self._active_idx >= len(self._segments):
            return None
        return self._segments[self._active_idx].id
