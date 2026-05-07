"""InsertPlaybackController — 결합 시간축 위에서 메인/보조 player 동기화.

책임:
- 사이드카 변경 시 결합 시간축 segments 재계산
- 슬라이더 시크 (결합 ms) → 메인/보조 player 라우팅
- 메인 player position_changed → 결합 ms 로 변환해 emit
- 보조 player position_changed → insert 진입 중일 때 결합 ms 로 변환해 emit

자동 전환 (insert 진입/이탈) 은 on_main_position_changed / on_insert_position_changed
가 segment 경계 도달 시 처리 — Task 3 에서 추가.

UI 위젯 의존을 회피하기 위해 main_player / insert_host 를 추상 인터페이스로 받음.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ...effects import Sidecar
from ...effects.timeline import (
    TimelineSegment, build_combined_timeline,
    combined_to_source, source_to_combined,
)
from ...effects.types.cut import CutEffect


class InsertPlaybackController(QObject):
    """결합 시간축 위에서 메인/보조 player 를 동기화."""

    combined_position_changed = Signal(int)      # ms — 결합 시간축
    combined_duration_changed = Signal(int)      # ms

    def __init__(self, main_player, insert_host) -> None:
        """main_player 는 PlayerWidget(메인 영상 + 슬라이더용 position_ms 제공),
        insert_host 도 PlayerWidget(보조 영상 + set_insert_source/seek/play API).
        실 구현에서는 둘 다 같은 PlayerWidget 인스턴스이지만, 테스트 분리를 위해
        별도 인자."""
        super().__init__()
        self._main = main_player
        self._insert = insert_host
        self._segments: list[TimelineSegment] = []
        self._main_duration_ms: int = 0
        self._cuts_by_id: dict[str, CutEffect] = {}
        self._active_cut_id: Optional[str] = None     # 현재 insert 재생 중인 cut

    # ---------- public ----------
    def set_sidecar(self, sidecar: Sidecar, main_duration_ms: int) -> None:
        """사이드카 변경 시 결합 시간축 재계산."""
        cuts = [e for e in sidecar.effects if isinstance(e, CutEffect)]
        self._cuts_by_id = {c.id: c for c in cuts}
        self._main_duration_ms = max(0, int(main_duration_ms))
        self._segments = build_combined_timeline(self._main_duration_ms, cuts)
        self.combined_duration_changed.emit(self.combined_duration_ms())

    def combined_duration_ms(self) -> int:
        if not self._segments:
            return self._main_duration_ms
        return self._segments[-1].combined_end_ms

    def seek_combined_ms(self, t_combined: int) -> None:
        """슬라이더 드래그 → 결합 ms → 적절한 player 로 시크."""
        if not self._segments:
            self._insert.show_insert_surface(False)
            self._main.seek_ms(int(t_combined))
            self._active_cut_id = None
            return
        source, source_id, source_ms = combined_to_source(int(t_combined), self._segments)
        if source == "main":
            # 보조 비활성화는 idempotent — 이미 꺼진 상태면 no-op.
            # active_cut_id 와 무관하게 항상 호출해 슬라이더 시크의 의도를 명시.
            self._insert.pause_insert()
            self._insert.show_insert_surface(False)
            self._active_cut_id = None
            self._main.seek_ms(int(source_ms))
        else:  # insert
            cut = self._cuts_by_id.get(source_id)
            if cut is None:
                return
            self._main.pause()
            self._main.seek_ms(int(cut.out_ms))
            if self._active_cut_id != cut.id:
                self._insert.set_insert_source(
                    Path(cut.src), seek_ms=int(source_ms), play_after_load=False,
                )
                self._active_cut_id = cut.id
            else:
                self._insert.seek_insert_ms(int(source_ms))
            self._insert.show_insert_surface(True)

    def on_main_position_changed(self, ms: int) -> None:
        if not self._segments:
            self.combined_position_changed.emit(int(ms))
            return
        if self._active_cut_id is not None:
            return
        # 진입점 검사 — 다음 cut 의 in_ms 도달?
        next_cut = self._next_cut_at_or_after(int(ms))
        if next_cut is not None and ms >= next_cut.in_ms:
            self._enter_insert(next_cut)
            return
        try:
            t = source_to_combined("main", None, int(ms), self._segments)
        except ValueError:
            return
        self.combined_position_changed.emit(int(t))

    def on_insert_position_changed(self, ms: int) -> None:
        if self._active_cut_id is None:
            return
        cut = self._cuts_by_id.get(self._active_cut_id)
        if cut is None:
            return
        end_ms = cut.src_out_ms or cut.src_duration_ms
        if end_ms > 0 and ms >= end_ms:
            self._exit_insert(cut)
            return
        try:
            t = source_to_combined("insert", self._active_cut_id, int(ms), self._segments)
        except ValueError:
            return
        self.combined_position_changed.emit(int(t))

    # ---------- internal ----------
    def _next_cut_at_or_after(self, main_ms: int) -> Optional[CutEffect]:
        """현재 main_ms 위치의 cut (또는 그 이후 가장 가까운). 정렬된 self._cuts_by_id
        에서 in_ms <= main_ms 인 가장 큰 in_ms 를 갖는 cut 을 반환 — main 이 막
        진입점에 닿았는지 검사 용."""
        best: Optional[CutEffect] = None
        for c in self._cuts_by_id.values():
            if c.in_ms <= main_ms and (best is None or c.in_ms > best.in_ms):
                # 이미 지나간 cut 이면 무시. main 이 cut 직후 위치라면 best = 그 cut.
                if main_ms <= c.out_ms or c.is_splice:
                    best = c
                elif main_ms == c.in_ms:
                    best = c
        return best

    def _enter_insert(self, cut: CutEffect) -> None:
        """insert 진입 — 메인 pause, 보조 setSource + play."""
        self._main.pause()
        if not cut.has_insert:
            # 단순 자르기 — insert 없이 그냥 cut.out_ms 로 건너뛴다.
            self._main.seek_ms(int(cut.out_ms))
            self._main.play()
            return
        self._insert.set_insert_source(
            Path(cut.src),
            seek_ms=int(cut.src_in_ms),
            play_after_load=True,
        )
        self._insert.show_insert_surface(True)
        self._active_cut_id = cut.id

    def _exit_insert(self, cut: CutEffect) -> None:
        """insert 이탈 — 보조 정지·숨김, 메인 cut.out_ms 로 시크 후 재개."""
        self._insert.pause_insert()
        self._insert.show_insert_surface(False)
        self._main.seek_ms(int(cut.out_ms))
        self._main.play()
        self._active_cut_id = None
