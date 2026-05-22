"""backend factory — runtime.py 에서 추출한 backend 생성 / tools dict 빌드 / 의존성 레이블.

ModelMetadata.runtime 값에 따라 ChatBackend 인스턴스를 반환하고,
backend 별로 다른 tools dict 형식을 조립한다.

외부에서 이 모듈만 import 하면 새 backend 추가 시 runtime.py 는 건드리지 않아도 됨.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import ChatBackend
from .claude_backend import ClaudeBackend
from .ollama_backend import OllamaBackend
from .transformers_backend import TransformersBackend

if TYPE_CHECKING:
    from ..models.metadata import ModelMetadata


# 사용자에게 표시할 의존성 안내 레이블 — 설치 안내 메시지에 그대로 삽입.
_DEPENDENCY_LABELS: dict[str, str] = {
    "transformers": "PyTorch + transformers + qwen_omni_utils",
    "llama-cpp": "llama-cpp-python",
    "ollama": "httpx (Ollama 클라이언트)",
}


def create_backend(meta: "ModelMetadata", cwd) -> ChatBackend:
    """ModelMetadata.runtime 에 따라 ChatBackend 인스턴스를 반환.

    - "claude": ClaudeBackend(cwd=cwd)
    - "transformers": TransformersBackend(repo_id=meta.repo_id, ...)
    - "ollama": OllamaBackend(model_tag=meta.repo_id)
    - 그 외: NotImplementedError

    의존성 가드는 set_model 진입점에서 — 여기는 순수 factory.
    """
    if meta.runtime == "claude":
        return ClaudeBackend(cwd=cwd)

    if meta.runtime == "transformers":
        if not meta.repo_id:
            raise ValueError(f"transformers 백엔드 모델인데 repo_id 누락: {meta.id}")
        # metadata.quantization 에 '4-bit' 들어 있으면 bitsandbytes NF4 로드.
        # 별도 ModelMetadata bool field 두지 않고 표시용 문자열을 single source of truth 로.
        load_in_4bit = "4-bit" in (meta.quantization or "")  # ★ 의도된 SSOT — 변경 금지
        return TransformersBackend(
            repo_id=meta.repo_id,
            modalities=meta.modalities,
            load_in_4bit=load_in_4bit,
        )

    if meta.runtime == "ollama":
        if not meta.repo_id:
            raise ValueError(f"ollama 백엔드 모델인데 model tag (repo_id) 누락: {meta.id}")
        return OllamaBackend(model_tag=meta.repo_id)

    raise NotImplementedError(
        f"runtime '{meta.runtime}' (모델 {meta.id}) — 미지원"
    )


def build_backend_tools(meta: "ModelMetadata", video_tools) -> dict:
    """ModelMetadata.runtime 에 따라 backend 별 tools dict 조립.

    - claude: {"mcp_server", "allowed_tools"}
    - transformers / llama-cpp / ollama: {"openai_tools", "tool_handlers", "tool_strategy"}
    - 그 외: 빈 dict
    """
    if meta.runtime == "claude":
        return {
            "mcp_server": video_tools.mcp_server(),
            "allowed_tools": video_tools.tool_names(),
        }

    if meta.runtime in ("transformers", "llama-cpp", "ollama"):
        openai_tools, handlers = video_tools.openai_tools_and_handlers()
        return {
            "openai_tools": openai_tools,
            "tool_handlers": handlers,
            "tool_strategy": meta.tool_strategy,
        }

    return {}


def runtime_dependency_label(runtime: str) -> str:
    """사용자에게 보여줄 runtime 의존성 설명 레이블.

    알려진 runtime 이면 _DEPENDENCY_LABELS 에서 반환,
    모르는 값이면 runtime 값 그대로 반환.
    """
    return _DEPENDENCY_LABELS.get(runtime, runtime)
