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
        """텍스트 메시지 처리. 이미지/멀티모달은 후속 task."""
        self._current_task = asyncio.current_task()
        try:
            await self._send_message_impl(msg, emit_fn)
        except asyncio.CancelledError:
            from ..runtime import AgentEvent
            emit_fn(AgentEvent(kind="error", detail="사용자가 취소함"))
            await self.close()
            raise
        finally:
            self._current_task = None

    async def _send_message_impl(self, msg: ChatInput, emit_fn: EmitFn) -> None:
        from ..runtime import AgentMessage, AgentEvent
        try:
            from claude_agent_sdk import (
                ClaudeAgentOptions, ClaudeSDKClient,
                AssistantMessage, ResultMessage, UserMessage, StreamEvent,
                TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock,
            )
        except Exception as exc:
            _log.exception("ClaudeBackend: SDK import 실패")
            emit_fn(AgentEvent(kind="error", detail=f"SDK import 실패: {exc}"))
            return

        try:
            if self._client is None:
                mcp_servers = {}
                allowed = []
                if self._tools:
                    mcp = self._tools.get("mcp_server")
                    if mcp is not None:
                        mcp_servers = {"kstudio_video": mcp}
                    allowed = list(self._tools.get("allowed_tools") or [])
                opts = ClaudeAgentOptions(
                    mcp_servers=mcp_servers,
                    allowed_tools=allowed,
                    cwd=str(self._cwd) if self._cwd else None,
                    env={"ANTHROPIC_API_KEY": ""},   # 정액제 강제
                    model=self._model,
                    include_partial_messages=True,
                    system_prompt=self._system_prompt,
                )
                # connect 실패 시 self._client 에 broken 객체 남기지 않기 — 다음 호출이 재연결 시도.
                client = ClaudeSDKClient(options=opts)
                try:
                    await client.connect()
                except Exception:
                    self._client = None
                    raise
                self._client = client

            emit_fn(AgentEvent(kind="started"))

            # 텍스트 query 만 (이미지는 task 8).
            await self._client.query(msg.text)

            # 응답 루프 — task 4~7 에서 분기 추가.
            async for sdk_msg in self._client.receive_response():
                if isinstance(sdk_msg, AssistantMessage):
                    for block in getattr(sdk_msg, "content", []) or []:
                        if isinstance(block, TextBlock):
                            text = getattr(block, "text", "")
                            if text:
                                emit_fn(AgentMessage(role="assistant", text=text))
                elif isinstance(sdk_msg, ResultMessage):
                    usage = getattr(sdk_msg, "usage", None) or {}
                    detail_parts = []
                    if usage:
                        in_t = int(usage.get("input_tokens") or 0)
                        out_t = int(usage.get("output_tokens") or 0)
                        if in_t or out_t:
                            detail_parts.append(f"in={in_t}")
                            detail_parts.append(f"out={out_t}")
                    emit_fn(AgentEvent(kind="done", detail=" ".join(detail_parts)))
                    break
        except Exception as exc:
            _log.exception("ClaudeBackend: query 실패")
            emit_fn(AgentEvent(kind="error", detail=str(exc)))

    async def send_tool_result(
        self, tool_use_id: str, result: Any, emit_fn: EmitFn,
    ) -> None:
        """다음 task 에서 구현 — 지금은 미완성."""
        raise NotImplementedError("Task 6 에서 구현")
