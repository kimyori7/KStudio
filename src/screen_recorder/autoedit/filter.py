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


def _snap_to_nearest_beat(ms: int, beats: list[tuple[int, float]], confidence: float, max_delta_ms: int = 200) -> int:
    """가장 가까운 비트가 max_delta_ms 안이면 snap, 아니면 원본 ms."""
    valid = [b for b, c in beats if c >= confidence]
    if not valid:
        return ms
    closest = min(valid, key=lambda b: abs(b - ms))
    return closest if abs(closest - ms) <= max_delta_ms else ms


def apply_thresholds(raw: AutoEditResult, s: AutoEditSettings) -> list:
    """raw → 사용자 설정 적용된 Effect 리스트."""
    effects: list = []
    if s.silence_enabled:
        effects.extend(_silence_to_cuts(raw, s))
    if s.caption_enabled:
        captions = _transcript_to_captions(raw, s)
        # BPM 활성 시 caption.in_ms 를 가까운 비트로 snap (±200ms).
        if s.bpm_enabled and raw.beats:
            from dataclasses import replace
            snapped = []
            for c in captions:
                new_in = _snap_to_nearest_beat(c.in_ms, raw.beats, s.bpm_confidence)
                snapped.append(replace(c, in_ms=new_in))
            captions = snapped
        effects.extend(captions)
    if s.scene_enabled:
        effects.extend(_scenes_to_zooms(raw, s))
    return effects


def _wrap_text_for_caption(text: str, max_chars: int) -> str:
    """한 자막 안에서 max_chars 단위로 줄바꿈.

    1순위: 공백 단위 (영문/한글 띄어쓰기 보존).
    각 단어가 max_chars 보다 길거나 공백 없는 텍스트는 char-level fallback.
    """
    if len(text) <= max_chars:
        return text
    words = text.split()
    if len(words) > 1:
        lines: list[str] = []
        cur = ""
        for w in words:
            if not cur:
                cur = w
            elif len(cur) + 1 + len(w) <= max_chars:
                cur += " " + w
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        # 단어 wrap 성공 시 (모든 줄이 max_chars 안) 반환.
        if all(len(l) <= max_chars for l in lines):
            return "\n".join(lines)
    # 공백 없는 텍스트 (한국어 한 덩어리) — char-level 분할 fallback.
    return "\n".join(text[i:i + max_chars] for i in range(0, len(text), max_chars))


def _transcript_to_captions(raw: AutoEditResult, s: AutoEditSettings) -> list:
    """Whisper transcript segments → CaptionEffect.

    한 자막 = 한 Whisper segment. text 가 caption_max_chars 초과 시 한 자막 *안에서*
    줄바꿈 (\\n) — 시간 분할 X. 사용자 기대: '한 줄 최대 N자' = 자동 줄바꿈.
    """
    from ..effects.types.caption import CaptionEffect, Font
    out = []
    max_chars = max(1, s.caption_max_chars)
    for seg in raw.transcript_segments:
        text = seg.get("text", "")
        in_ms = int(seg.get("in_ms", 0))
        out_ms = int(seg.get("out_ms", in_ms + 1000))
        if not text:
            continue
        wrapped = _wrap_text_for_caption(text, max_chars)
        out.append(CaptionEffect(
            id=str(uuid4()),
            in_ms=in_ms,
            out_ms=out_ms,
            text=wrapped,
            font=Font(),
        ))
    return out


def _scenes_to_zooms(raw: AutoEditResult, s: AutoEditSettings) -> list:
    """씬 시작 지점 → magnify_region ZoomEffect (가운데 60% 영역 → 화면 가득).

    sensitivity 이상 score 만 통과. 지속 2초 고정.

    ZoomEffect 에는 region_cx/region_cy 필드가 없다 (center 는 ZoomPoint.cx/cy).
    region_w/region_h 만 지정 — 중심은 기본값 0.5/0.5 (start/end ZoomPoint 기본값).
    """
    from ..effects.types.zoom import ZoomEffect, ZoomPoint
    out = []
    for ms, score in raw.scene_changes:
        if score < s.scene_sensitivity:
            continue
        out.append(ZoomEffect(
            id=str(uuid4()),
            in_ms=ms,
            out_ms=ms + 2000,
            mode="magnify_region",
            region_w=0.6,
            region_h=0.6,
            dest_cx=0.5,
            dest_cy=0.5,
            dest_w=1.0,
            dest_h=1.0,
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
