"""모델 메타데이터 — built-in + 사용자 추가 모델 공통 표현.

sub-plan 4 의 user_models.json 직렬화도 같은 dataclass 사용.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ModelMetadata:
    """모델 라이브러리의 한 항목.

    runtime: "claude" | "transformers" | "llama-cpp" — backend factory 가 이 값으로
             라우팅. "llama-cpp" 는 sub-plan 5 까지 미사용.
    repo_id: HuggingFace repo (claude 는 None).
    estimated_size_gb: UI 표시용 (claude=0).
    """
    id: str
    display_name: str
    runtime: str
    repo_id: Optional[str]
    modalities: frozenset[str]
    supports_korean: bool
    estimated_size_gb: float
    estimated_vram_gb: float
    context_window: int
    supports_tools: bool
    description: str
    source: str = "builtin"
    quantization: Optional[str] = None
