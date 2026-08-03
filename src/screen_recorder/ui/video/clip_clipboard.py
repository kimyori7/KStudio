"""ClipClipboard — 영상 탭 사이를 건너다니는 타임라인 클립보드 (프로세스 전역 1개).

영상 A 에서 클립을 복사해 영상 B 에 붙여넣으려면 클립보드가 탭 밖에 살아야 한다.
VideoTab 인스턴스가 들고 있으면 탭을 옮기는 순간 사라진다 (2026-08-03 사용자 요청:
"잘라낸 걸 복사해서 다른 영상에 붙이고 싶다").

담는 것은 둘 중 하나 — 마지막 복사가 이전 것을 덮어쓴다:
- segment: 영상 트랙의 클립 1개 + 그 구간에 완전히 들어 있던 효과들
- effect:  캡션/줌/배속/화살표 등 효과 1개

segment 와 함께 담는 효과의 in_ms/out_ms 는 **클립 시작 기준 local ms** 로 rebase 해
둔다. 붙여넣는 쪽은 트랙상 시작 위치만 더하면 되고, 원본 클립이 트랙 어디에 있었는지
알 필요가 없다.

take_* 는 호출할 때마다 새 id 를 부여한 deep copy 를 돌려준다 — 같은 클립을 여러 번
붙여넣어도 id 가 충돌하지 않고, 클립보드 원본은 그대로 남아 반복 붙여넣기가 된다.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import replace
from typing import Optional

from ...effects.model import Effect
from ...effects.segment import VideoSegment


class ClipClipboard:
    """복사된 클립/효과 1개를 보관. 인스턴스는 보통 모듈 싱글턴 하나 (clipboard())."""

    def __init__(self) -> None:
        self._kind: Optional[str] = None          # "segment" | "effect" | None
        self._segment: Optional[VideoSegment] = None
        self._effects: list[Effect] = []          # segment 동반 효과 (local ms)
        self._effect: Optional[Effect] = None

    # ---------- 담기 ----------
    def copy_segment(self, segment: VideoSegment, effects=()) -> None:
        """클립 1개 + 동반 효과를 담는다. effects 의 ms 는 **트랙(combined) 기준** 으로
        받아 클립 시작 기준 local ms 로 rebase 한다.

        길이가 0 인 클립은 붙여넣어 봐야 1px 조각이 되어 되살릴 방법이 없으므로 거부한다
        (호출자가 ffprobe 로 길이를 채운 뒤 넘겨야 한다).
        """
        if segment.duration_ms <= 0:
            raise ValueError(
                f"길이 0 인 클립은 복사할 수 없다 (src={segment.src!r}) — "
                "src_duration_ms 를 채운 뒤 호출할 것"
            )
        base = int(segment.start_ms)
        self._kind = "segment"
        self._segment = copy.deepcopy(segment)
        self._effects = [
            replace(copy.deepcopy(e),
                    in_ms=int(e.in_ms) - base, out_ms=int(e.out_ms) - base)
            for e in effects
        ]
        self._effect = None

    def copy_effect(self, effect: Effect) -> None:
        """효과 1개를 담는다 (ms 는 손대지 않음 — 붙여넣기 쪽이 위치를 정한다)."""
        self._kind = "effect"
        self._effect = copy.deepcopy(effect)
        self._segment = None
        self._effects = []

    def clear(self) -> None:
        self._kind = None
        self._segment = None
        self._effects = []
        self._effect = None

    # ---------- 꺼내기 ----------
    def kind(self) -> Optional[str]:
        """"segment" | "effect" | None (비어 있음)."""
        return self._kind

    def take_segment(self) -> Optional[tuple[VideoSegment, list[Effect]]]:
        """새 id 를 부여한 (클립, 동반 효과들) 사본. 효과 ms 는 여전히 local 기준.

        kind 가 segment 가 아니면 None.
        """
        if self._kind != "segment" or self._segment is None:
            return None
        seg = replace(copy.deepcopy(self._segment), id=uuid.uuid4().hex)
        # 효과 id 도 새로 — 중복 id 면 Del 한 번에 원본까지 같이 지워진다
        # (remove_effect 는 id 로 필터링).
        effs = [replace(copy.deepcopy(e), id=str(uuid.uuid4())) for e in self._effects]
        return seg, effs

    def take_effect(self) -> Optional[Effect]:
        """새 id 를 부여한 효과 사본. kind 가 effect 가 아니면 None."""
        if self._kind != "effect" or self._effect is None:
            return None
        return replace(copy.deepcopy(self._effect), id=str(uuid.uuid4()))

    def peek_effect(self) -> Optional[Effect]:
        """담긴 효과 원본 (id 그대로) — 테스트/표시용. 붙여넣기엔 take_effect 를 쓸 것."""
        return self._effect


_CLIPBOARD = ClipClipboard()


def clipboard() -> ClipClipboard:
    """프로세스 전역 클립보드. 모든 VideoTab 이 같은 인스턴스를 본다."""
    return _CLIPBOARD
