"""백엔드 공통 — multi-round tool use 루프.

각 backend 가 같은 패턴 갖던 것:
  for round in range(MAX_ROUNDS):
      text, calls = await generate_once()
      if not calls:
          emit done; return
      await handle_calls(calls)
  emit "한계 초과"

backend 가 generate 와 handle_calls 만 구현하면 됨. history append / message shape /
malformed retry 같은 backend 별 분기는 generate / handle_calls 안에서 처리.

순수 stateless helper — Qt / 직접 모델 호출 없음.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from .base import AgentEvent, AgentMessage


# 모든 local backend 공통 안전망. 5 라운드면 일반 작업에 충분.
DEFAULT_MAX_TOOL_ROUNDS = 5


async def run_tool_loop(
    generate_once: Callable[[], Awaitable[tuple[str, list[dict]]]],
    on_tool_calls: Callable[[list[dict]], Awaitable[None]],
    emit_fn: Callable[[Any], None],
    max_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
) -> None:
    """generate → tool_calls 처리 반복. tool_calls 비면 done emit 후 종료.

    generate_once: (full_text, tool_calls_list) 반환. tool_calls 가 빈 list 면
                   최종 응답 — done emit 후 루프 종료.
    on_tool_calls: tool_calls 를 받아 handler 실행 + conversation append. backend 가
                   message shape (Qwen vs Ollama) 결정.
    emit_fn: AgentMessage / AgentEvent 발행 (UI 콜백).
    max_rounds: 안전망 — 초과 시 system 메시지 + done emit.

    cancel 처리는 호출자가 generate_once 안에서 — 여기는 단순 루프만.
    """
    for _round in range(max_rounds):
        _full_text, tool_calls = await generate_once()
        if not tool_calls:
            emit_fn(AgentEvent(kind="done"))
            return
        await on_tool_calls(tool_calls)

    emit_fn(AgentMessage(
        role="system",
        text=f"⚠ 도구 호출 루프 한계 ({max_rounds} 라운드) 초과 — 중단.",
    ))
    emit_fn(AgentEvent(kind="done"))
