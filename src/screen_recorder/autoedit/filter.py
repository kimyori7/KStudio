"""raw AutoEditResult + AutoEditSettings → list[Effect].

핵심: 분석 재실행 없음. 슬라이더 변경 → 이 함수만 재호출 → UI 갱신.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
from uuid import uuid4

from .result import AutoEditResult
from .presets import AutoEditSettings

if TYPE_CHECKING:
    from ..effects.types.base import Effect


def apply_thresholds(raw: AutoEditResult, s: AutoEditSettings) -> list:
    """raw → 사용자 설정 적용된 Effect 리스트."""
    effects: list = []
    if s.silence_enabled:
        effects.extend(_silence_to_cuts(raw, s))
    # caption / scene / bpm 은 후속 Phase 에서 채움.
    return effects


def _silence_to_cuts(raw: AutoEditResult, s: AutoEditSettings) -> list:
    """무음 구간 → CutEffect."""
    from ..effects.types.cut import CutEffect
    out = []
    for start_ms, end_ms in raw.silence_segments:
        if end_ms - start_ms < s.silence_min_ms:
            continue
        out.append(CutEffect(
            id=str(uuid4()),
            in_ms=start_ms,
            out_ms=end_ms,
            src="",
        ))
    return out
