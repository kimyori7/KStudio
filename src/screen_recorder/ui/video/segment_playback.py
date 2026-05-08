"""SegmentPlaybackController — video_track 의 segment 를 순차 재생.

기존 InsertPlaybackController (메인+보조 player) 를 대체. 트랙 모델에선 모든 segment 가
동등하므로 player 1개면 충분 — 다음 segment 로 넘어갈 때 setSource + seek 만.

책임:
- 결합 시간축 (segment 의 duration_ms 누적합) 계산 + 외부에 emit
- 메인 player position → 결합 ms 변환 + segment 끝 도달 시 다음 segment 로 자동 전환
- 사용자 시크 (combined_ms) → 적절한 segment 에 source switch + seek

UI 의존을 회피하기 위해 player 는 추상 인터페이스 (PlayerWidget) 로 받음.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ...effects import Sidecar
from ...effects.segment import VideoSegment


class SegmentPlaybackController(QObject):
    """단일 player + segment 순차 재생."""

    combined_position_changed = Signal(int)      # 결합 시간축 ms
    combined_duration_changed = Signal(int)
    active_segment_changed = Signal(str)         # segment id (재생 중 segment)

    def __init__(self, player) -> None:
        """player 는 PlayerWidget — load(path), seek_ms(ms), play(), pause(),
        position_ms(), duration_ms() 메서드 제공. position_changed Signal 지원."""
        super().__init__()
        self._player = player
        self._segments: list[VideoSegment] = []
        self._active_idx: int = -1   # 현재 로드된 segment 의 인덱스
        self._loaded_src: Optional[str] = None
        # autoplay 재시작 — segment 전환 시 메인이 pause 된 상태면 그대로, play 면 play.
        self._was_playing: bool = False

    # ---------- public ----------
    def set_sidecar(self, sidecar: Sidecar) -> None:
        """사이드카 변경 시 segment 리스트 갱신 + 결합 길이 emit."""
        self._segments = list(sidecar.video_track)
        self.combined_duration_changed.emit(self.combined_duration_ms())
        # 현재 재생 중인 segment id 가 새 리스트에 없으면 첫 segment 로 reset.
        if self._active_idx >= len(self._segments):
            self._active_idx = -1
            self._loaded_src = None

    def combined_duration_ms(self) -> int:
        return sum(max(0, s.duration_ms) for s in self._segments)

    def seek_combined_ms(self, t_combined: int) -> None:
        """슬라이더 시크 → 적절한 segment 로 source switch + seek."""
        idx, local_ms = self._combined_to_segment_local(int(t_combined))
        if idx < 0:
            return
        self._activate_segment(idx, seek_local_ms=local_ms)

    def on_main_position_changed(self, ms: int) -> None:
        """player 의 position 변화 — 결합 ms 로 변환 emit + segment 끝 검사."""
        if self._active_idx < 0 or not self._segments:
            self.combined_position_changed.emit(int(ms))
            return
        seg = self._segments[self._active_idx]
        local_ms = max(0, int(ms) - int(seg.src_in_ms))
        # 결합 ms = 이전 segment 들의 duration 합 + local_ms.
        combined_offset = sum(s.duration_ms for s in self._segments[:self._active_idx])
        combined = combined_offset + local_ms
        self.combined_position_changed.emit(int(combined))
        # segment 끝 도달 → 다음 segment 로 자동 전환.
        seg_dur = seg.duration_ms
        if seg_dur > 0 and local_ms >= seg_dur:
            next_idx = self._active_idx + 1
            if next_idx < len(self._segments):
                self._activate_segment(next_idx, seek_local_ms=0)
            else:
                # 마지막 segment 끝 — pause.
                self._player.pause()

    # ---------- internal ----------
    def _combined_to_segment_local(self, t_combined: int) -> tuple[int, int]:
        """결합 ms → (segment_idx, segment-local ms). 빈 segments 면 (-1, 0)."""
        if not self._segments:
            return (-1, 0)
        cursor = 0
        for i, s in enumerate(self._segments):
            dur = s.duration_ms
            if cursor + dur > t_combined or i == len(self._segments) - 1:
                return (i, max(0, int(t_combined) - cursor))
            cursor += dur
        return (-1, 0)

    def _activate_segment(self, idx: int, *, seek_local_ms: int = 0) -> None:
        """segment 를 활성화 — source 가 다르면 load, 같으면 seek 만."""
        if not (0 <= idx < len(self._segments)):
            return
        seg = self._segments[idx]
        target_src = seg.src
        target_seek_ms = int(seg.src_in_ms) + max(0, seek_local_ms)
        if self._loaded_src != target_src:
            self._player.load(Path(target_src))
            self._loaded_src = target_src
        self._player.seek_ms(int(target_seek_ms))
        self._active_idx = idx
        self.active_segment_changed.emit(seg.id)

    @property
    def active_segment_id(self) -> Optional[str]:
        if self._active_idx < 0 or self._active_idx >= len(self._segments):
            return None
        return self._segments[self._active_idx].id
