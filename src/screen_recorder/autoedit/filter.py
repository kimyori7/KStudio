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
    if s.caption_enabled:
        effects.extend(_transcript_to_captions(raw, s))
    # scene / bpm 은 후속 Phase 에서 채움.
    return effects


def _transcript_to_captions(raw: AutoEditResult, s: AutoEditSettings) -> list:
    """Whisper transcript segments → CaptionEffect.

    한 줄 글자수 (s.caption_max_chars) 초과 시 균등 분할. 시간도 균등 분할.
    """
    from ..effects.types.caption import CaptionEffect, Font
    out = []
    for seg in raw.transcript_segments:
        text = seg.get("text", "")
        in_ms = int(seg.get("in_ms", 0))
        out_ms = int(seg.get("out_ms", in_ms + 1000))
        if not text:
            continue
        # max_chars 초과 시 균등 분할.
        max_chars = max(1, s.caption_max_chars)
        if len(text) <= max_chars:
            chunks = [text]
        else:
            n = (len(text) + max_chars - 1) // max_chars
            chunk_len = (len(text) + n - 1) // n
            chunks = [text[i:i + chunk_len] for i in range(0, len(text), chunk_len)]
        # 시간도 균등 분할.
        total = max(1, out_ms - in_ms)
        per = total // len(chunks)
        for i, ch in enumerate(chunks):
            start = in_ms + i * per
            end = in_ms + (i + 1) * per if i < len(chunks) - 1 else out_ms
            out.append(CaptionEffect(
                id=str(uuid4()),
                in_ms=start,
                out_ms=end,
                text=ch,
                font=Font(),
            ))
    return out


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
