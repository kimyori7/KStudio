"""ClaudeBackend — claude_agent_sdk 래퍼.

기존 runtime.py 의 _run_query_impl + _disconnect_client + helpers 를 이 모듈로 이동.
Qt 의존 없음 — emit_fn 콜백으로 이벤트 전달.

스레드 모델: 호출자 (runtime.py 의 worker thread) 가 자체 asyncio loop 위에서
이 메서드들을 await. 백엔드 자체는 thread 비인지 — asyncio 만 알면 됨.
"""
from __future__ import annotations

import asyncio
import base64
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
        # 동시 send() 두 번 → 두 코루틴 모두 client 생성 → leak. Lock 으로 직렬화.
        self._connect_lock = asyncio.Lock()

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
            async with self._connect_lock:
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

            # 이미지 첨부 있으면 multipart 메시지 형식.
            if msg.images:
                content_blocks: list[dict] = []
                for img_bytes in msg.images:
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": _sniff_image_mime(img_bytes),
                            "data": base64.b64encode(img_bytes).decode("ascii"),
                        },
                    })
                content_blocks.append({"type": "text", "text": msg.text or "(첨부 이미지 참고)"})

                async def _multipart_iter():
                    yield {
                        "type": "user",
                        "message": {"role": "user", "content": content_blocks},
                        "parent_tool_use_id": None,
                    }

                await self._client.query(_multipart_iter())
            else:
                await self._client.query(msg.text)

            # 텍스트/thinking 가 partial 로 도착 — 중복 방지 플래그.
            text_streamed = False
            thinking_streamed = False
            last_am_total_input = 0   # 마지막 AssistantMessage 의 input_tokens + cache 합

            # 응답 루프 — task 4~7 에서 분기 추가.
            async for sdk_msg in self._client.receive_response():
                if isinstance(sdk_msg, StreamEvent):
                    ev = sdk_msg.event or {}
                    ev_type = ev.get("type")
                    if ev_type == "message_start":
                        text_streamed = False
                        thinking_streamed = False
                    elif ev_type == "content_block_delta":
                        delta = ev.get("delta") or {}
                        d_type = delta.get("type")
                        if d_type == "text_delta":
                            chunk = delta.get("text") or ""
                            if chunk:
                                text_streamed = True
                                emit_fn(AgentMessage(role="assistant", text=chunk))
                        elif d_type == "thinking_delta":
                            chunk = delta.get("thinking") or ""
                            if chunk:
                                thinking_streamed = True
                                emit_fn(AgentMessage(role="thinking", text=chunk))
                    # 외 stream event (content_block_start/stop, message_delta/stop 등) skip.
                    continue

                if isinstance(sdk_msg, AssistantMessage):
                    # 마지막 AM 의 usage 가 *한 번의 API 호출* context size — 200k 안에서 정확.
                    # SDK ResultMessage.usage 는 한 응답 안 여러 API 호출 (도구 호출마다 1번) 의
                    # input_tokens 를 *합산* 해서 줌 → 도구 5번이면 5번의 context size 합쳐져
                    # 200k 초과 가능 (사용자 보고 2026-05-13: 166% 표시). 각 AM 의 usage 는 단일
                    # API 호출 한 번의 context 라 200k 안에서 정확.
                    am_usage = getattr(sdk_msg, "usage", None)
                    if isinstance(am_usage, dict):
                        last_am_total_input = (
                            int(am_usage.get("input_tokens") or 0)
                            + int(am_usage.get("cache_read_input_tokens") or 0)
                            + int(am_usage.get("cache_creation_input_tokens") or 0)
                        )
                    for block in getattr(sdk_msg, "content", []) or []:
                        if isinstance(block, ThinkingBlock):
                            # partial 로 이미 그림 — 중복 방지 (Task 4 의 thinking_streamed 플래그 사용).
                            if thinking_streamed:
                                continue
                            txt = getattr(block, "thinking", "") or getattr(block, "text", "")
                            if txt:
                                emit_fn(AgentMessage(role="thinking", text=str(txt)))
                        elif isinstance(block, TextBlock):
                            # partial 로 이미 그림 — 중복 방지.
                            if text_streamed:
                                continue
                            text = getattr(block, "text", "")
                            if text:
                                emit_fn(AgentMessage(role="assistant", text=text))
                        elif isinstance(block, ToolUseBlock):
                            name = getattr(block, "name", "?")
                            input_dict = getattr(block, "input", {}) or {}
                            emit_fn(AgentEvent(
                                kind="tool_use",
                                detail=f"{name} {_short_args(input_dict)}",
                            ))
                            emit_fn(AgentMessage(
                                role="tool_use",
                                text=f"🔧 {name}({_short_args(input_dict)})",
                                tool_name=name,
                            ))
                elif isinstance(sdk_msg, UserMessage):
                    for block in getattr(sdk_msg, "content", []) or []:
                        if isinstance(block, ToolResultBlock):
                            tool_id = getattr(block, "tool_use_id", "")
                            content = getattr(block, "content", None)
                            img_bytes, img_mime, preview = _extract_image_and_preview(content)
                            emit_fn(AgentMessage(
                                role="tool_result",
                                text=f"← {preview}",
                                tool_name=tool_id,
                                image_bytes=img_bytes,
                                image_mime=img_mime,
                            ))
                elif isinstance(sdk_msg, ResultMessage):
                    usage = getattr(sdk_msg, "usage", None) or {}
                    detail_parts = []
                    if isinstance(usage, dict):
                        in_t = int(usage.get("input_tokens") or 0)
                        cache_read = int(usage.get("cache_read_input_tokens") or 0)
                        cache_create = int(usage.get("cache_creation_input_tokens") or 0)
                        out_t = int(usage.get("output_tokens") or 0)
                        total_in = in_t + cache_read + cache_create
                        if total_in or out_t:
                            detail_parts.append(f"in={total_in}")
                            detail_parts.append(f"out={out_t}")
                    # last_in — 컨텍스트 % 표시용. SDK 합산 over-count 회피.
                    if last_am_total_input > 0:
                        detail_parts.append(f"last_in={last_am_total_input}")
                    emit_fn(AgentEvent(kind="done", detail=" ".join(detail_parts)))
                    break
        except Exception as exc:
            _log.exception("ClaudeBackend: query 실패")
            emit_fn(AgentEvent(kind="error", detail=str(exc)))

    async def send_tool_result(
        self, tool_use_id: str, result: Any, emit_fn: EmitFn,
    ) -> None:
        """도구 결과를 Claude 에 회신 — runtime.py 의 in-process MCP 도구가 자체 응답하는
        경우와 별개로, 사용자 ✓ 게이트 같이 외부 동기화 필요한 도구를 위한 경로.

        현재 KStudio 의 모든 MCP 도구는 in-process 라 SDK 가 자동 회신 → 이 메서드는
        향후 비-MCP 도구 (예: plan_gate 의 비동기 응답) 추가 시 사용. 지금은 단순 stub.
        """
        # SDK 의 in-process MCP 도구는 자체 응답하므로 별도 동작 없음.
        # 비-MCP 외부 도구 추가될 때 (sub-plan 6 tool adapter) 채워질 예정.
        _log.debug("send_tool_result called (no-op for in-process MCP): tool_use_id=%s result=%r",
                    tool_use_id, result)


def _sniff_image_mime(data: bytes) -> str:
    """이미지 bytes 의 magic number 보고 MIME 추정.

    Anthropic API 가 image content block 의 media_type 을 검사 — 잘못된 선언이면
    reject. 현재 chat_panel 은 항상 PNG 로 저장하지만 향후 file-attach 같은 경로에서
    JPEG 가 들어올 수 있음. fallback 은 PNG (가장 흔한 케이스).
    """
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 2 and data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"   # safe default


def _short_args(d: dict) -> str:
    """도구 호출 인자 짧게 (인스펙터용).

    runtime.py 에서 이동 (Task 5). 한 줄 표시 위해 최대 4개 키 + 각 값 40자 cap.
    """
    if not d:
        return ""
    parts = []
    for k, v in list(d.items())[:4]:
        sv = repr(v)
        if len(sv) > 40:
            sv = sv[:37] + "..."
        parts.append(f"{k}={sv}")
    return ", ".join(parts)


def _extract_image_and_preview(content: Any) -> tuple[Optional[bytes], Optional[str], str]:
    """tool_result content 에서 (image_bytes, mime, text_preview) 추출.

    content 가 list[dict] 일 때 (MCP 표준):
    - text 블록 → preview 누적
    - image 블록 → base64 → bytes 디코드, mime 저장 (한 장만 처리)
    문자열이면 그대로 preview.

    runtime.py 에서 이동 (Task 6). Task 9 에서 runtime.py 원본 삭제.
    """
    if content is None:
        return None, None, "(없음)"
    if isinstance(content, str):
        return None, None, content[:120] + ("…" if len(content) > 120 else "")
    img_bytes: Optional[bytes] = None
    img_mime: Optional[str] = None
    text_parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "image" and img_bytes is None:
                data = block.get("data")
                mime = block.get("mimeType") or block.get("mime_type") or "image/png"
                if isinstance(data, str) and data:
                    try:
                        img_bytes = base64.b64decode(data)
                        img_mime = str(mime)
                    except Exception:
                        pass
            elif btype == "text":
                text_parts.append(str(block.get("text", "")))
    preview = " ".join(text_parts).strip()
    if not preview:
        preview = "[이미지]" if img_bytes else "(빈 결과)"
    elif len(preview) > 120:
        preview = preview[:117] + "…"
    return img_bytes, img_mime, preview
