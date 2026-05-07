"""같은 종류 효과의 시간 겹침 검사 — UI 추가/이동 전에 호출."""
from __future__ import annotations
from typing import Iterable

from .model import Effect


def overlaps_existing(existing: Iterable[Effect], candidate: Effect) -> bool:
    """candidate 와 같은 type 의 existing 중 시간이 겹치는 게 있으면 True.

    같은 id(자기 자신) 는 제외 — 시간 이동 시 자기 자신과의 비교를 막음.
    구간 [in, out) 반열림 — 끝점 = 시작점 일 땐 안 겹침.
    """
    cin, cout = candidate.in_ms, candidate.out_ms
    for e in existing:
        if e.id == candidate.id:
            continue
        if e.type != candidate.type:
            continue
        # 구간 [in, out) 겹침: not (cout <= e.in_ms or cin >= e.out_ms)
        if not (cout <= e.in_ms or cin >= e.out_ms):
            return True
    return False
