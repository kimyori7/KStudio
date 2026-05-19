"""Plan-Gate 가 propose_* 도구를 차단하는지 + submit_plan 응답.

mutation 도구는 asyncio 함수라 pytest-asyncio 없이 asyncio.run() 으로 직접 await.
"""
from __future__ import annotations

import asyncio
import threading
import pytest

from screen_recorder.agent.adapter import VideoSessionAdapter
from screen_recorder.agent.plan_gate import PlanGate
from screen_recorder.agent.proposals import ProposalQueue
from screen_recorder.agent.tools.mutation import make_mutation_tools


class _StubAdapter(VideoSessionAdapter):
    """최소 stub — has_active_video True 만 반환."""
    def has_active_video(self) -> bool:
        return True
    def active_video_path(self) -> str:
        return "/fake.mp4"
    def active_sidecar(self) -> dict:
        return {"effects": []}
    def active_duration_ms(self) -> int:
        return 60_000
    def active_position_ms(self) -> int:
        return 0
    def active_source_duration_ms(self) -> int:
        return 60_000


def _make_tools(plan_gate: PlanGate):
    """tools list 를 dict[name → fn] 으로."""
    adapter = _StubAdapter()
    queue = ProposalQueue()
    tools = make_mutation_tools(adapter, queue, None, plan_gate)
    return {t.name: t for t in tools}, queue


def _invoke(tool_fn, args: dict) -> dict:
    """sdk @tool 데코레이터로 감싼 함수 호출 — asyncio.run 으로 sync 래핑."""
    return asyncio.run(tool_fn.handler(args))


def test_propose_effect_blocked_without_plan() -> None:
    g = PlanGate()
    tools, queue = _make_tools(g)
    result = _invoke(tools["propose_effect"], {
        "type": "caption",
        "payload": {"in_ms": 0, "out_ms": 1000, "text": "hi"},
    })
    text = result["content"][0]["text"]
    assert "submit_plan" in text
    assert queue.count() == 0


def test_propose_effect_passes_after_approve() -> None:
    g = PlanGate()
    tools, queue = _make_tools(g)
    # submit() requires a running loop now (Task 1 fix).
    async def go():
        pid = g.submit("s", "m")
        g.approve(pid)
    asyncio.run(go())
    result = _invoke(tools["propose_effect"], {
        "type": "caption",
        "payload": {"in_ms": 0, "out_ms": 1000, "text": "hi"},
    })
    text = result["content"][0]["text"]
    assert "queued" in text.lower() or "true" in text.lower()
    assert queue.count() == 1


def test_propose_remove_blocked_without_plan() -> None:
    g = PlanGate()
    tools, _q = _make_tools(g)
    result = _invoke(tools["propose_remove_effect"], {"effect_id": "x"})
    assert "submit_plan" in result["content"][0]["text"]


def test_propose_modify_blocked_without_plan() -> None:
    g = PlanGate()
    tools, _q = _make_tools(g)
    result = _invoke(tools["propose_modify_effect"], {
        "effect_id": "x", "payload": {"text": "y"},
    })
    assert "submit_plan" in result["content"][0]["text"]


def test_apply_proposals_blocked_without_plan() -> None:
    g = PlanGate()
    tools, _q = _make_tools(g)
    result = _invoke(tools["apply_proposals"], {})
    assert "submit_plan" in result["content"][0]["text"]


def test_list_proposals_allowed_without_plan() -> None:
    """list_proposals 는 read-only — plan 없이 OK."""
    g = PlanGate()
    tools, _q = _make_tools(g)
    result = _invoke(tools["list_proposals"], {})
    text = result["content"][0]["text"]
    assert "count" in text.lower()


def test_discard_proposals_allowed_without_plan() -> None:
    """discard 는 cancellation — plan 없이 OK (사용자 변심 정리 자유)."""
    g = PlanGate()
    tools, _q = _make_tools(g)
    result = _invoke(tools["discard_proposals"], {})
    text = result["content"][0]["text"]
    assert "discarded" in text.lower()


def test_invalidate_re_blocks_after_approve() -> None:
    """approve 후 invalidate → 다시 propose 차단."""
    g = PlanGate()
    tools, queue = _make_tools(g)

    async def first():
        pid = g.submit("s", "m")
        g.approve(pid)
    asyncio.run(first())

    result1 = _invoke(tools["propose_effect"], {
        "type": "caption",
        "payload": {"in_ms": 0, "out_ms": 1000, "text": "a"},
    })
    assert queue.count() == 1

    g.invalidate_approval()
    result2 = _invoke(tools["propose_effect"], {
        "type": "caption",
        "payload": {"in_ms": 1000, "out_ms": 2000, "text": "b"},
    })
    text2 = result2["content"][0]["text"]
    assert "submit_plan" in text2
    assert queue.count() == 1


def test_submit_plan_tool_returns_approved_after_user_approve() -> None:
    """submit_plan 도구 — 별도 task 에서 approve → 도구가 approved:true dict 반환."""
    g = PlanGate()
    tools, _q = _make_tools(g)

    async def call_submit():
        async def approve_after_delay():
            await asyncio.sleep(0.05)
            with g._lock:
                pids = list(g._pending.keys())
            assert pids, "submit_plan 이 PlanGate.submit 호출했어야"
            g.approve(pids[0])
        asyncio.create_task(approve_after_delay())
        return await tools["submit_plan"].handler({
            "summary": "필러 cut", "markdown": "1. cut\n2. cut",
        })

    result = asyncio.run(call_submit())
    text = result["content"][0]["text"]
    assert "approved" in text.lower()
    assert "true" in text.lower()


def test_submit_plan_tool_returns_reason_after_user_reject() -> None:
    g = PlanGate()
    tools, _q = _make_tools(g)

    async def call_submit():
        async def reject_after_delay():
            await asyncio.sleep(0.05)
            with g._lock:
                pids = list(g._pending.keys())
            g.reject(pids[0], "필러는 빼지마")
        asyncio.create_task(reject_after_delay())
        return await tools["submit_plan"].handler({
            "summary": "s", "markdown": "m",
        })

    result = asyncio.run(call_submit())
    text = result["content"][0]["text"]
    assert "approved" in text.lower()
    assert "false" in text.lower()
    assert "필러는 빼지마" in text
