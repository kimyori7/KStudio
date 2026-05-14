"""Claude Agent 임베드 UI — 채팅 패널 + 도구 호출 인디케이터.

Phase A (2026-05-13): ChatPanel QDockWidget. AgentRuntime 의 시그널에 반응해
메시지 리스트 갱신.
"""
from .chat_panel import ChatPanel

__all__ = ["ChatPanel"]
