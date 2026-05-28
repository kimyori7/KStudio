"""ModelRegistry — built-in 4개 + (sub-plan 4 에서) 사용자 추가 모델 머지.

check_runtime_available(runtime) 도 여기 — 의존성 import 시도.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
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
        # bf16 + device_map="auto" — accelerate 가 자연스럽게 talker (speech 전용,
        # 안 씀) 를 CPU 로 보내 GPU ~7-8GB 만 사용. 2026-05-22 시도한 4-bit 양자화
        # (llm_int8_enable_fp32_cpu_offload) 는 매 forward 마다 dequantize 임시 buffer 가
        # GPU 에 올라가 spillover + KV cache 누적 → 사용자 환경 (가용 VRAM 7.5GB) 에서
        # 메모리 폭증 + 단어 3중 반복 (spillover 로 generate 망가짐). 회귀로 되돌림.
        # 4-bit 옵션 자체 (TransformersBackend.load_in_4bit) 는 코드에 남겨둠 — 다른
        # GPU 환경 (가용 14GB+) 사용자가 quantization 필드 "4-bit" 로 바꾸면 사용 가능.
        quantization="bf16 (원본)",
        modalities=frozenset({"text", "image", "audio", "video"}),
        supports_korean=True,
        estimated_size_gb=22.4, estimated_vram_gb=14.0,
        context_window=32_768,
        supports_tools=True,
        description=(
            "영상/오디오 native + 도구 호출 (prompt 시뮬레이션). bf16 원본 로드 — "
            "accelerate 가 device_map=auto 로 talker 자동 CPU offload → 실 사용 ~7-8GB."
        ),
        tool_strategy="prompted",
    ),
    ModelMetadata(
        id="qwen3-vl-2b-instruct",
        display_name="Qwen3-VL 2B (로컬, 가장 가벼움)",
        runtime="transformers",
        repo_id="Qwen/Qwen3-VL-2B-Instruct",
        # 2B bf16 ~4GB. KStudio 비디오 디코더 + Qt + KV cache 합쳐도 5060 Ti 16GB 에
        # 절반 이상 여유. 4B 가 다른 process 와 합쳐 spillover 일으킨 사용자 환경
        # (2026-05-26) 의 안전 옵션. 품질은 4B 보다 약간 낮지만 frame 분석엔 충분.
        quantization="bf16 (원본)",
        modalities=frozenset({"text", "image", "video"}),
        supports_korean=True,
        estimated_size_gb=3.5, estimated_vram_gb=6.0,
        context_window=256_000,
        supports_tools=True,
        description=(
            "VL 최경량 (2B). VRAM 부족 환경에 우선 시도. 영상 frame 분석 + 한국어 OK. "
            "4B 가 spillover 일으키는 사용자는 이걸로 갈아타면 여유 있게 동작."
        ),
        # VL 모델은 작아서 chat_template 의 tools= 만으론 도구 호출 형식 안 따라옴
        # (사용자 보고 2026-05-26: <tool_call> 태그 0 회). prompted 로 강제 → system
        # prompt 에 도구 카탈로그 + Hermes 형식 예시 직접 주입 → 따라할 확률 ↑.
        tool_strategy="prompted",
    ),
    ModelMetadata(
        id="qwen3-vl-4b-instruct",
        display_name="Qwen3-VL 4B (로컬, 비전+영상)",
        runtime="transformers",
        repo_id="Qwen/Qwen3-VL-4B-Instruct",
        # bf16 원본 — 4B 라 ~8GB. RTX 5060 Ti 가용 VRAM 7.5GB 환경에 통째로 fit 목표
        # (Omni 7B 는 CPU offload 불가피해서 느림). VL family 는 audio native X — 영상은
        # 시각 프레임만 분석 (KStudio 의 Whisper 가 오디오 전사를 별도로 담당).
        # Qwen2.5 디코더 계승 → 한국어 OK. 도구 호출은 tool_strategy="prompted"
        # (VL 모델은 official 만으론 도구 호출 형식 안 따라옴 — prompted 가 카탈로그 명시).
        quantization="bf16 (원본)",
        modalities=frozenset({"text", "image", "video"}),
        supports_korean=True,
        # estimated_size_gb=5.5 — 사용자 실측 (2026-05-26): HF cache dedup 적용 시 ~5.1GB.
        # 여유 0.4GB. 추정과 실제가 크게 다르면 progress bar 가 100% 못 채움 → "멈춤" 오해.
        # estimated_vram_gb=11 — 사용자 실측 (2026-05-26): 가중치 8GB + ViT 0.6-1GB +
        # CUDA context 0.5-1GB + caching allocator 여유 + KV cache + activations. 처음
        # 7GB 로 추정했으나 inference 시 실제로는 ~10-12GB. 5060 Ti 16GB 에 여유 fit.
        estimated_size_gb=5.5, estimated_vram_gb=11.0,
        context_window=256_000,
        supports_tools=True,
        description=(
            "비전·영상 특화 (1h+ 동영상 이해, 시각 frame 분석). bf16 ~7GB 로 5060 Ti 가용 "
            "VRAM 안에 통째로 fit → Omni 보다 빠름. 오디오 native 없음 — Whisper 로 우회."
        ),
        # VL 모델은 official 만으론 도구 호출 형식 안 따라옴 (사용자 보고 2026-05-26).
        # prompted 가 system prompt 에 카탈로그 + Hermes 형식 예시 명시 → 모델이 따라할 확률 ↑.
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
    """runtime 의 의존성 모듈이 모두 설치되어 있는지 — backend 활성화 가드용.

    return: True 면 backend 인스턴스화 가능. False 면 ChatPanel 이 가드 시스템
    메시지 emit + 콤보 fallback.

    "llama-cpp" 등 미구현 runtime 은 False.

    구현 (2026-05-22 변경): `importlib.util.find_spec` 사용 — disk 의 .dist-info /
    __init__.py 위치만 확인. 실제 import 안 함 → torch 같이 CUDA driver init 으로
    수십 초 걸리는 무거운 모듈도 ms 단위. KStudio 시작 시 ChatPanel 의 모델 콤보가
    각 모델 메타에 대해 호출하므로 가벼움이 중요. 이전엔 `importlib.import_module`
    실제 호출 → 첫 부팅 시 transformers + torch + qwen_omni_utils 까지 강제 import
    → 시작 지연 10~30초 (사용자 보고).
    """
    deps = _RUNTIME_DEPS.get(runtime)
    if not deps:
        return False
    for mod_name in deps:
        # 이미 import 됐거나 테스트가 sys.modules 에 mock inject 한 경우 — 통과.
        # find_spec 은 sys.modules 에 있는 모듈의 __spec__ attribute 를 참조 →
        # mock object 면 ValueError. 그 가드 위해 sys.modules 먼저 확인.
        if mod_name in sys.modules:
            continue
        try:
            spec = importlib.util.find_spec(mod_name)
        except (ImportError, ValueError):
            _log.debug("check_runtime_available(%s): %s find_spec 실패", runtime, mod_name)
            return False
        if spec is None:
            _log.debug("check_runtime_available(%s): missing %s", runtime, mod_name)
            return False
    return True
