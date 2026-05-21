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
    # tool use 처리 방식 — "none" (도구 불가), "official" (chat_template 의 tools=
    # 인자 정식 지원, Hermes 형식 자동 출력), "prompted" (chat_template 미지원 →
    # KStudio 가 system prompt 에 도구 카탈로그 주입 + 출력에서 <tool_call> 태그
    # 수동 파싱). 출력 파싱은 두 경우 동일 — 차이는 prompt 구성뿐.
    tool_strategy: str = "none"
