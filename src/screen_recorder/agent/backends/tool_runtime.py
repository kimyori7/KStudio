"""백엔드 공통 — tool call 실행 + UI emit + 결과 직렬화.

Transformers / Ollama 가 같은 방식으로 handler 호출하고 결과를 emit 해야 하는데
3번씩 복제되는 것 막기 위함. message shape (conversation 에 어떻게 append 할지) 는
각 backend 가 결정 — 이 helper 는 **실행 + UI emit + body 직렬화** 까지만.

순수 함수 모음 — Qt 의존 없음.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from .base import AgentEvent, AgentMessage


_log = logging.getLogger(__name__)


@dataclass
class NormalizedToolCall:
    """backend 별 tool_call shape (Hermes <tool_call> vs Ollama tool_calls) 흡수.

    id: tool_use_id (Hermes 는 tu_0/tu_1, Ollama 는 모델이 안 주면 None 가능).
    name: 정규화된 도구 이름 (mcp prefix 없음).
    arguments: dict — handler 에 그대로 전달.
    """
    id: str | None
    name: str
    arguments: dict


async def execute_tool_call(
    call: NormalizedToolCall,
    handlers: dict[str, Callable[[dict], Any]],
    emit_fn: Callable[[Any], None],
) -> str:
    """call 실행 → emit (tool_use → tool_result) → 직렬화된 body 반환.

    반환 body 는 backend 가 conversation 에 append 할 때 그대로 사용.
    - handler 가 dict 반환 → JSON 문자열.
    - handler 가 str 반환 → 그대로.
    - 예외 → `{"error": "<msg>"}` 직렬화.
    - 미등록 handler → `{"error": "unknown tool: <name>"}`.
    """
    args = call.arguments
    name = call.name

    # tool_use UI emit (event + message 둘 다 — chat_panel 호환).
    emit_fn(AgentEvent(kind="tool_use", detail=f"{name} {args}"))
    emit_fn(AgentMessage(
        role="tool_use",
        text=f"🔧 {name}({args})",
        tool_name=name,
    ))

    handler = handlers.get(name)
    if handler is None:
        result_val: Any = {"error": f"unknown tool: {name}"}
    else:
        try:
            ret = handler(args)
            if asyncio.iscoroutine(ret):
                ret = await ret
            result_val = ret
        except Exception as exc:
            _log.exception("tool handler 실패: %s", name)
            result_val = {"error": str(exc)}

    # body 직렬화 (string 은 그대로, 나머지는 JSON).
    if isinstance(result_val, str):
        body = result_val
    else:
        body = json.dumps(result_val, ensure_ascii=False, default=str)

    # tool_result UI emit — preview 200자.
    preview = body[:200]
    emit_fn(AgentMessage(
        role="tool_result",
        text=f"← {preview}",
        tool_name=name,
    ))

    return body
