"""AutoEditResult — 모든 analyzer 의 raw 결과를 모은 dataclass.

slider 임계값 변경 시 메모리 필터링만 (재분석 없음). 디스크 캐시 단위.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class AutoEditResult:
    source_hash: str
    # SilenceAnalyzer: (start_ms, end_ms) tuples — 무음 구간.
    silence_segments: list[tuple[int, int]] = field(default_factory=list)
    # TranscriptAnalyzer: [{in_ms, out_ms, text}, ...] — Whisper segments.
    transcript_segments: list[dict[str, Any]] = field(default_factory=list)
    # SceneAnalyzer: (ms, score) — 씬 시작 지점 + 변화 강도.
    scene_changes: list[tuple[int, float]] = field(default_factory=list)
    # BPMAnalyzer: (ms, confidence) — 비트 시점 + 신뢰도.
    beats: list[tuple[int, float]] = field(default_factory=list)
    # 분석 메타 — 캐시 키 일부 + 사용자 표시.
    analyzer_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AutoEditResult":
        # tuple round-trip: JSON 에서 list 로 돌아오므로 명시 변환.
        d = dict(d)
        d["silence_segments"] = [tuple(x) for x in d.get("silence_segments", [])]
        d["scene_changes"] = [tuple(x) for x in d.get("scene_changes", [])]
        d["beats"] = [tuple(x) for x in d.get("beats", [])]
        return cls(**d)
