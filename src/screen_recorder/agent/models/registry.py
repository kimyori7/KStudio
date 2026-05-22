"""ModelRegistry — built-in 4개 + (sub-plan 4 에서) 사용자 추가 모델 머지.

check_runtime_available(runtime) 도 여기 — 의존성 import 시도.
"""
from __future__ import annotations

import importlib
import logging
from typing import Optional

from .metadata import ModelMetadata


_log = logging.getLogger(__name__)


_BUILTIN: list[ModelMetadata] = [
    ModelMetadata(
        id="claude-opus-4-7",
        display_name="Claude — Opus 4.7",
        runtime="claude", repo_id=None,
        modalities=frozenset({"text", "image"}),
        supports_korean=True,
        estimated_size_gb=0, estimated_vram_gb=0,
        context_window=1_000_000,
        supports_tools=True,
        description="가장 정밀한 편집 도구 호출. 영상은 스크린샷으로만.",
    ),
    ModelMetadata(
        id="claude-sonnet-4-6",
        display_name="Claude — Sonnet 4.6",
        runtime="claude", repo_id=None,
        modalities=frozenset({"text", "image"}),
        supports_korean=True,
        estimated_size_gb=0, estimated_vram_gb=0,
        context_window=200_000,
        supports_tools=True,
        description="속도/품질 균형. 정액제 친화적 기본.",
    ),
    ModelMetadata(
        id="claude-haiku-4-5-20251001",
        display_name="Claude — Haiku 4.5",
        runtime="claude", repo_id=None,
        modalities=frozenset({"text", "image"}),
        supports_korean=True,
        estimated_size_gb=0, estimated_vram_gb=0,
        context_window=200_000,
        supports_tools=True,
        description="가장 빠름. 간단한 질문/요약에.",
    ),
    ModelMetadata(
        id="qwen25-7b-instruct",
        display_name="Qwen2.5 7B Instruct (로컬, 텍스트)",
        runtime="transformers",
        repo_id="Qwen/Qwen2.5-7B-Instruct",
        quantization="bf16 (원본)",
        modalities=frozenset({"text"}),
        supports_korean=True,
        estimated_size_gb=15.5, estimated_vram_gb=9.0,
        context_window=32_768,
        supports_tools=True,
        description="텍스트 전용. KStudio 도구 정식 호출 (Hermes 형식). 영상/이미지 분석 불가.",
        tool_strategy="official",
    ),
    ModelMetadata(
        id="qwen25-omni-7b",
        display_name="Qwen2.5-Omni 7B (로컬, 멀티모달)",
        runtime="transformers",
        repo_id="Qwen/Qwen2.5-Omni-7B",
        quantization="bf16 (원본)",
        modalities=frozenset({"text", "image", "audio", "video"}),
        supports_korean=True,
        estimated_size_gb=22.4, estimated_vram_gb=14.0,
        context_window=32_768,
        supports_tools=True,
        description="영상/오디오 native. ~22GB 다운로드, bf16 로드. 도구 호출은 prompt 시뮬레이션 (정식 미지원).",
        tool_strategy="prompted",
    ),
    ModelMetadata(
        id="qwen3-8b-ollama",
        display_name="Qwen3 8B (Ollama, 빠름)",
        runtime="ollama",
        # repo_id 자리에 Ollama 태그를 둠 — Ollama 가 자체 모델 스토어 관리하므로 HF
        # 다운로드 X. 사용 전 사용자가 'ollama pull qwen3:8b' 수동 실행 필요.
        repo_id="qwen3:8b",
        quantization="Q4_K_M (Ollama 기본)",
        modalities=frozenset({"text"}),
        supports_korean=True,
        estimated_size_gb=5.2, estimated_vram_gb=6.0,
        context_window=32_768,
        supports_tools=True,
        description=(
            "Ollama 백엔드 — GGUF + llama.cpp 로 transformers (bf16) 보다 5~10배 빠름. "
            "도구 호출 정식 지원 (Qwen3 chat_template + Ollama native). "
            "사전 요구: Ollama 설치 + `ollama serve` 동작 + `ollama pull qwen3:8b`."
        ),
        tool_strategy="official",
    ),
]


_RUNTIME_DEPS: dict[str, tuple[str, ...]] = {
    "claude": ("claude_agent_sdk",),
    "transformers": ("transformers", "torch", "qwen_omni_utils"),
    # Ollama 백엔드는 httpx 만 있으면 OK — 서버 자체 (ollama.exe) 는 Python dep 아님.
    # 서버 reachability 는 send_message 시점에 ConnectError 로 친절히 안내.
    "ollama": ("httpx",),
}


class ModelRegistry:
    """모델 메타데이터 컨테이너. 현재는 built-in 만 — sub-plan 4 가 user_models.json 머지 추가."""

    def all_models(self) -> list[ModelMetadata]:
        return list(_BUILTIN)

    def get(self, model_id: str) -> Optional[ModelMetadata]:
        for m in _BUILTIN:
            if m.id == model_id:
                return m
        return None


def check_runtime_available(runtime: str) -> bool:
    """runtime 의 의존성 모듈이 모두 import 가능한지 — backend 활성화 가드용.

    return: True 면 backend 인스턴스화 가능. False 면 ChatPanel 이 가드 시스템
    메시지 emit + 콤보 fallback.

    "llama-cpp" 등 미구현 runtime 은 False.
    """
    deps = _RUNTIME_DEPS.get(runtime)
    if not deps:
        return False
    for mod_name in deps:
        try:
            importlib.import_module(mod_name)
        except ImportError:
            _log.debug("check_runtime_available(%s): missing %s", runtime, mod_name)
            return False
    return True
