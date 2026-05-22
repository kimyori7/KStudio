"""execute_tool_call — handler 호출, 예외 처리, emit, preview."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest


def _collect_emits() -> tuple[list[Any], "callable"]:
    seen: list[Any] = []
    def emit(item):
        seen.append(item)
    return seen, emit


@pytest.mark.asyncio
async def test_execute_returns_dict_result_and_emits_tool_use_then_result():
    from screen_recorder.agent.backends.tool_runtime import (
        NormalizedToolCall, execute_tool_call,
    )
    seen, emit = _collect_emits()
    handlers = {"get_video_state": lambda args: {"duration_ms": 12345}}
    call = NormalizedToolCall(id="tu_0", name="get_video_state", arguments={})

    body = await execute_tool_call(call, handlers, emit)
    assert '"duration_ms": 12345' in body
    # emit 순서: tool_use(message) → tool_result(message). event 도 함께.
    roles = [getattr(m, "role", None) for m in seen]
    assert "tool_use" in roles
    assert "tool_result" in roles


@pytest.mark.asyncio
async def test_execute_with_async_handler_awaits():
    from screen_recorder.agent.backends.tool_runtime import (
        NormalizedToolCall, execute_tool_call,
    )
    async def _h(args): return {"ok": True}
    _, emit = _collect_emits()
    body = await execute_tool_call(
        NormalizedToolCall(id="tu_0", name="x", arguments={}),
        {"x": _h}, emit,
    )
    assert '"ok": true' in body


@pytest.mark.asyncio
async def test_execute_handler_exception_emits_error_dict():
    from screen_recorder.agent.backends.tool_runtime import (
        NormalizedToolCall, execute_tool_call,
    )
    def _boom(args): raise RuntimeError("nope")
    _, emit = _collect_emits()
    body = await execute_tool_call(
        NormalizedToolCall(id="tu_0", name="x", arguments={}),
        {"x": _boom}, emit,
    )
    assert "nope" in body
    assert "error" in body


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_error_marker():
    from screen_recorder.agent.backends.tool_runtime import (
        NormalizedToolCall, execute_tool_call,
    )
    _, emit = _collect_emits()
    body = await execute_tool_call(
        NormalizedToolCall(id="tu_0", name="missing", arguments={}),
        {}, emit,
    )
    assert "unknown tool" in body


@pytest.mark.asyncio
async def test_execute_emits_tool_use_before_tool_result():
    """tool_use emit 이 tool_result emit 보다 먼저 와야 한다 (순서 보장)."""
    from screen_recorder.agent.backends.tool_runtime import (
        NormalizedToolCall, execute_tool_call,
    )
    from screen_recorder.agent.backends.base import AgentMessage
    seen, emit = _collect_emits()
    handlers = {"foo": lambda args: {"x": 1}}
    call = NormalizedToolCall(id="tu_0", name="foo", arguments={})

    await execute_tool_call(call, handlers, emit)

    msgs = [m for m in seen if isinstance(m, AgentMessage)]
    roles = [m.role for m in msgs]
    # tool_use 가 tool_result 보다 먼저.
    assert "tool_use" in roles
    assert "tool_result" in roles
    assert roles.index("tool_use") < roles.index("tool_result")


@pytest.mark.asyncio
async def test_execute_string_handler_result_passes_through():
    """handler 가 str 반환하면 JSON 인코딩 없이 그대로 body 로."""
    from screen_recorder.agent.backends.tool_runtime import (
        NormalizedToolCall, execute_tool_call,
    )
    _, emit = _collect_emits()
    body = await execute_tool_call(
        NormalizedToolCall(id="tu_0", name="x", arguments={}),
        {"x": lambda args: "raw string result"},
        emit,
    )
    assert body == "raw string result"
