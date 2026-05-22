"""ChatBackend 추상화 — 백엔드 (Claude SDK / transformers / llama-cpp 등) 통합 인터페이스.

각 백엔드는 ChatBackend Protocol 을 구현하고 사용자 메시지를 받아 SDK/모델별 호출 후
AgentMessage/AgentEvent emit. runtime.py 의 Agent 가 backend 한 개를 보유하고 위임.
"""
from .base import AgentEvent, AgentMessage, ChatBackend, ChatInput, EmitFn
from .claude_backend import ClaudeBackend
from .ollama_backend import OllamaBackend
from .transformers_backend import TransformersBackend

__all__ = [
    "AgentEvent", "AgentMessage",
    "ChatBackend", "ChatInput", "EmitFn",
    "ClaudeBackend", "TransformersBackend", "OllamaBackend",
]
