"""자동편집 임계값 기본값 + 사용자 설정 dataclass.

메인테이너 가이드: 임계값 바꾸려면 이 파일만 수정 — 다른 곳에서 직접 숫자 넣지 말 것.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class AutoEditSettings:
    """사용자가 리뷰 다이얼로그에서 조정 가능한 모든 임계값."""
    silence_enabled: bool = True
    silence_min_ms: int = 800
    caption_enabled: bool = True
    caption_max_chars: int = 30
    caption_split: str = "sentence"     # "sentence" | "fixed_3s"
    scene_enabled: bool = True
    scene_sensitivity: int = 30
    scene_zoom_strength: float = 1.3
    bpm_enabled: bool = False
    bpm_confidence: float = 0.6


def default_settings() -> AutoEditSettings:
    return AutoEditSettings()
