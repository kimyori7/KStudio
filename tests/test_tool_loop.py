"""run_tool_loop — 한계 도달 / 정상 종료 / tool_calls 누적 동작."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_loop_returns_when_no_tool_calls():
    from screen_recorder.agent.backends.tool_loop import run_tool_loop
    from screen_recorder.agent.backends.base import AgentEvent

    seen = []
    async def _generate_once():
        return ("최종 답입니다", [])   # no tool calls
    async def _on_tool_calls(calls): pass

    emit = seen.append
    await run_tool_loop(_generate_once, _on_tool_calls, emit, max_rounds=5)

    done = [e for e in seen if isinstance(e, AgentEvent) and e.kind == "done"]
    assert len(done) == 1


@pytest.mark.asyncio
async def test_loop_invokes_on_tool_calls_until_empty():
    from screen_recorder.agent.backends.tool_loop import run_tool_loop

    rounds_remaining = [2]
    on_calls_invocations = []

    async def _generate_once():
        if rounds_remaining[0] > 0:
            rounds_remaining[0] -= 1
            return ("...", [{"name": "x", "arguments": {}}])
        return ("done", [])

    async def _on_tool_calls(calls):
        on_calls_invocations.append(len(calls))

    await run_tool_loop(_generate_once, _on_tool_calls, lambda x: None, max_rounds=5)
    assert on_calls_invocations == [1, 1]


@pytest.mark.asyncio
async def test_loop_max_rounds_emits_warning_and_done():
    from screen_recorder.agent.backends.tool_loop import run_tool_loop
    from screen_recorder.agent.backends.base import AgentMessage, AgentEvent

    seen = []
    async def _generate_once():
        return ("계속 도구만 부르네", [{"name": "x", "arguments": {}}])
    async def _on_tool_calls(calls): pass

    await run_tool_loop(_generate_once, _on_tool_calls, seen.append, max_rounds=2)

    warns = [m for m in seen if isinstance(m, AgentMessage) and m.role == "system"]
    assert any("루프 한계" in m.text for m in warns)
    done = [e for e in seen if isinstance(e, AgentEvent) and e.kind == "done"]
    assert len(done) == 1
