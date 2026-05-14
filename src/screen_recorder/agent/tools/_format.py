"""사람 읽을 수 있는 요약 + ms 포매팅 + 효과/세그먼트 summary dict.

읽기 도구가 텍스트 응답에 쓸 데이터 모양 표준화.
"""
from __future__ import annotations

from typing import Any

from ...effects.sidecar import Sidecar


_TYPE_LABEL_KO = {
    "cut": "자르기", "caption": "캡션", "speed": "배속",
    "zoom": "줌", "broll": "곁들임", "arrow": "화살표",
}


def format_ms_short(ms: int) -> str:
    """123_456 → '2:03.4' / 3_661_000 → '1:01:01'."""
    s_total = max(0, ms) // 1000
    if s_total >= 3600:
        h = s_total // 3600
        m = (s_total % 3600) // 60
        s = s_total % 60
        return f"{h}:{m:02d}:{s:02d}"
    m = s_total // 60
    s = s_total % 60
    t = (ms % 1000) // 100
    return f"{m}:{s:02d}.{t}"


def sidecar_summary_text(sc: Sidecar, duration_ms: int) -> str:
    """한 문단 요약 — Claude 가 항상-pin 으로 참조. ~150자.

    "영상 길이 X. 세그먼트 N개. 효과 M개 (캡션 a, 배속 b, ...)." 형태.
    """
    by_type: dict[str, list[Any]] = {}
    for e in sc.effects:
        t = str(getattr(e, "type", "unknown"))
        by_type.setdefault(t, []).append(e)
    parts: list[str] = []
    parts.append(f"영상 길이 {format_ms_short(duration_ms)}")
    parts.append(f"세그먼트 {len(sc.video_track)}개")
    if not sc.effects:
        parts.append("효과 없음")
    else:
        parts.append(f"효과 {len(sc.effects)}개")
        per_type_chunks: list[str] = []
        for t in ("cut", "caption", "speed", "zoom", "broll", "arrow"):
            n = len(by_type.get(t, []))
            if n > 0:
                per_type_chunks.append(f"{_TYPE_LABEL_KO.get(t, t)} {n}")
        if per_type_chunks:
            parts.append("(" + ", ".join(per_type_chunks) + ")")
    return ". ".join(parts) + "."


def segment_summary(seg: Any) -> dict[str, Any]:
    """VideoSegment → dict for tool response."""
    return {
        "id": getattr(seg, "id", ""),
        "src": getattr(seg, "src", ""),
        "start_ms": getattr(seg, "start_ms", 0),
        "duration_ms": getattr(seg, "duration_ms", 0),
        "src_in_ms": getattr(seg, "src_in_ms", 0),
        "src_out_ms": getattr(seg, "src_out_ms", 0),
        "media_kind": getattr(seg, "media_kind", "video"),
    }


def effect_summary(eff: Any) -> dict[str, Any]:
    """Effect → dict for tool response. type 별 특화 필드 (text/rate 등) 포함."""
    base = {
        "id": getattr(eff, "id", ""),
        "type": getattr(eff, "type", "unknown"),
        "in_ms": getattr(eff, "in_ms", 0),
        "out_ms": getattr(eff, "out_ms", 0),
        "track_idx": getattr(eff, "track_idx", 0),
    }
    text = getattr(eff, "text", None)
    if text is not None:
        base["text"] = text
    rate = getattr(eff, "rate", None)
    if rate is not None:
        base["rate"] = rate
    return base
