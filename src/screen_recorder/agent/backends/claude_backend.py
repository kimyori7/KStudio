"""ClaudeBackend — claude_agent_sdk 래퍼.

기존 runtime.py 의 _run_query_impl + _disconnect_client + helpers 를 이 모듈로 이동.
Qt 의존 없음 — emit_fn 콜백으로 이벤트 전달.

스레드 모델: 호출자 (runtime.py 의 worker thread) 가 자체 asyncio loop 위에서
이 메서드들을 await. 백엔드 자체는 thread 비인지 — asyncio 만 알면 됨.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from .base import ChatInput, EmitFn


_log = logging.getLogger(__name__)


class ClaudeBackend:
    """Anthropic Claude (claude_agent_sdk) 백엔드.

    수명주기:
    - start_session(): 옵션 저장만. 실제 client 연결은 첫 send_message 에서 lazy.
    - send_message(): query 송신 + receive_response 루프 + AgentMessage/AgentEvent emit.
    - cancel(): 진행 중 receive_response task 취소.
    - close(): client.disconnect() — 다음 send_message 가 재연결.
    """

    def __init__(self, cwd: Optional[str | Path] = None) -> None:
        # SDK 가 도구 실행 / 파일 접근 시 사용할 working directory. Task 3 의 connect 에 전달.
        self._cwd = Path(cwd) if cwd else None
        self._client: Optional[Any] = None     # ClaudeSDKClient — lazy import
        self._system_prompt: str = ""
        self._model: str = "sonnet"
        self._tools: dict[str, Any] = {}
        self._current_task: Optional[asyncio.Task] = None

    async def start_session(
        self, system_prompt: str, tools: dict[str, Any], model: str,
    ) -> None:
        """옵션 저장 + 기존 client 가 있으면 disconnect (재연결 강제).

        tools dict: {"mcp_server": Any, "allowed_tools": list[str]}.
        빈 dict 면 도구 없는 채팅 (PoC 테스트용).
        """
        self._system_prompt = system_prompt
        self._tools = tools or {}
        self._model = model
        # 모델 / 도구 / 시스템 프롬프트 변경 시 client 재연결 필요.
        if self._client is not None:
            await self.close()

    async def close(self) -> None:
        """client disconnect — 다음 send_message 가 재연결."""
        if self._client is None:
            return
        try:
            await self._client.disconnect()
        except Exception:
            _log.exception("ClaudeBackend: disconnect 실패 (무시)")
        self._client = None

    async def cancel(self) -> None:
        """진행 중 send_message 의 task 취소."""
        task = self._current_task
        if task is not None and not task.done():
            task.cancel()

    def supports_modality(self, modality: str) -> bool:
        # Claude — text + image. audio/video 는 향후 sub-plan 7 에서 frame 폴백.
        return modality == "image"

    async def send_message(self, msg: ChatInput, emit_fn: EmitFn) -> None:
        """다음 task 에서 구현 — 지금은 미완성."""
        raise NotImplementedError("Task 3 에서 구현")

    async def send_tool_result(
        self, tool_use_id: str, result: Any, emit_fn: EmitFn,
    ) -> None:
        """다음 task 에서 구현 — 지금은 미완성."""
        raise NotImplementedError("Task 6 에서 구현")
