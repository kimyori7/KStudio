"""PlanGate — worker↔UI bridge + 승인 상태 관리.

Phase 1 (이 파일): 순수 도메인 로직 (Qt Signal 없이).
"""
from __future__ import annotations

import asyncio
import threading
import pytest

from screen_recorder.agent.plan_gate import PlanGate, PlanDecision


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """asyncio.run() 으로 단일 coro 실행 — 새 loop 생성."""
    return asyncio.run(coro)


def _make_gate_with_pid() -> tuple[PlanGate, str]:
    """PlanGate + submit() 된 plan_id 를 async 컨텍스트 안에서 생성해 반환."""
    g = PlanGate()
    pid_holder: list[str] = []

    async def _inner():
        pid = g.submit("s", "m")
        pid_holder.append(pid)

    asyncio.run(_inner())
    return g, pid_holder[0]


# ---------------------------------------------------------------------------
# submit / plan_id
# ---------------------------------------------------------------------------

def test_submit_returns_unique_plan_id() -> None:
    pids: list[str] = []

    async def _inner():
        g = PlanGate()
        pids.append(g.submit("summary1", "markdown1"))
        pids.append(g.submit("summary2", "markdown2"))

    asyncio.run(_inner())
    pid1, pid2 = pids
    assert pid1 != pid2
    assert pid1.startswith("plan_")
    assert pid2.startswith("plan_")


# ---------------------------------------------------------------------------
# approve / reject / cancel_all  (async waiter + threaded UI)
# ---------------------------------------------------------------------------

def test_approve_resolves_future_with_approved_true() -> None:
    """submit → 별도 스레드에서 approve → await_decision 이 approved=True 반환."""
    g = PlanGate()

    async def waiter():
        pid = g.submit("s", "m")
        # approve 는 별도 스레드에서 (UI 시뮬레이션) — loop run 시작 후 잠깐 뒤.
        def approve_later():
            import time
            time.sleep(0.05)
            g.approve(pid)
        threading.Thread(target=approve_later).start()
        return await g.await_decision(pid)

    decision = asyncio.run(waiter())
    assert decision.approved is True
    assert decision.reason == ""


def test_reject_resolves_future_with_reason() -> None:
    g = PlanGate()

    async def waiter():
        pid = g.submit("s", "m")
        def reject_later():
            import time
            time.sleep(0.05)
            g.reject(pid, "이건 아니야")
        threading.Thread(target=reject_later).start()
        return await g.await_decision(pid)

    decision = asyncio.run(waiter())
    assert decision.approved is False
    assert decision.reason == "이건 아니야"


def test_cancel_all_rejects_pending_with_cancelled_reason() -> None:
    g = PlanGate()

    async def waiter():
        pid = g.submit("s", "m")
        def cancel_later():
            import time
            time.sleep(0.05)
            g.cancel_all()
        threading.Thread(target=cancel_later).start()
        return await g.await_decision(pid)

    decision = asyncio.run(waiter())
    assert decision.approved is False
    assert decision.reason == "cancelled"


# ---------------------------------------------------------------------------
# require_approval / invalidate_approval
# ---------------------------------------------------------------------------

def test_require_approval_raises_when_no_approval() -> None:
    g = PlanGate()
    with pytest.raises(ValueError) as exc:
        g.require_approval()
    assert "submit_plan" in str(exc.value)


def test_require_approval_passes_after_approve() -> None:
    async def _inner():
        g = PlanGate()
        pid = g.submit("s", "m")
        g.approve(pid)
        # require_approval 이 예외 안 던지면 통과.
        g.require_approval()

    asyncio.run(_inner())


def test_invalidate_approval_makes_require_fail_again() -> None:
    async def _inner():
        g = PlanGate()
        pid = g.submit("s", "m")
        g.approve(pid)
        g.require_approval()   # OK.
        g.invalidate_approval()
        with pytest.raises(ValueError):
            g.require_approval()

    asyncio.run(_inner())


def test_reject_does_not_change_last_approved() -> None:
    """reject 는 단지 future 만 해결 — 이전 approval 무효화 X."""
    async def _inner():
        g = PlanGate()
        pid1 = g.submit("s1", "m1")
        g.approve(pid1)
        pid2 = g.submit("s2", "m2")
        g.reject(pid2, "no")
        # 첫 plan 의 승인은 여전히 유효해야 함 — propose_* 통과 가능.
        g.require_approval()

    asyncio.run(_inner())


def test_two_plans_independent_decisions() -> None:
    """동시 2 plan — 각각 별도 future 해결."""
    g = PlanGate()

    async def both():
        pid1 = g.submit("s1", "m1")
        pid2 = g.submit("s2", "m2")

        def resolve_both():
            import time
            time.sleep(0.05)
            g.approve(pid1)
            g.reject(pid2, "two")
        threading.Thread(target=resolve_both).start()

        results = await asyncio.gather(
            g.await_decision(pid1), g.await_decision(pid2)
        )
        return results

    r1, r2 = asyncio.run(both())
    assert r1.approved is True
    assert r2.approved is False and r2.reason == "two"


def test_approve_unknown_plan_id_is_noop() -> None:
    """존재하지 않는 plan_id 로 approve → 조용히 무시 (race condition 방어)."""
    g = PlanGate()
    g.approve("plan_nonexistent")   # 예외 X.


def test_reject_unknown_plan_id_is_noop() -> None:
    g = PlanGate()
    g.reject("plan_nonexistent", "")   # 예외 X.


# ---------------------------------------------------------------------------
# Issue 1 regression: approve(unknown) must NOT open the gate
# ---------------------------------------------------------------------------

def test_approve_unknown_plan_id_does_not_open_gate() -> None:
    """Critical 회귀 보호 — unknown plan_id 로 approve 해도 gate 안 열림."""
    g = PlanGate()
    g.approve("plan_nonexistent")
    with pytest.raises(ValueError):
        g.require_approval()


# ---------------------------------------------------------------------------
# Issue 1 regression: cancel_all + late approve must NOT open the gate
# ---------------------------------------------------------------------------

def test_approve_after_cancel_all_does_not_open_gate() -> None:
    """cancel_all 로 비워진 후 UI 가 늦게 ✓ 누름 → gate 안 열림."""
    async def _inner():
        g = PlanGate()
        pid = g.submit("s", "m")
        g.cancel_all()
        g.approve(pid)   # 이미 cleared — should be noop.
        with pytest.raises(ValueError):
            g.require_approval()

    asyncio.run(_inner())


# ---------------------------------------------------------------------------
# Issue 3 regression: await_decision without submit raises ValueError
# ---------------------------------------------------------------------------

def test_await_decision_unknown_plan_id_raises() -> None:
    """submit() 안 거치고 await_decision 호출 → ValueError."""
    g = PlanGate()

    async def waiter():
        return await g.await_decision("plan_never_submitted")

    with pytest.raises(ValueError):
        asyncio.run(waiter())


# ============================================================
# Qt Signal — submit() 이 plan_submitted emit
# ============================================================
def test_submit_emits_plan_submitted_signal(qtbot) -> None:
    """submit() 호출 시 plan_submitted(plan_id, summary, markdown) Signal 발화."""
    import asyncio as _asyncio
    g = PlanGate()
    received: list[tuple] = []
    g.plan_submitted.connect(lambda pid, s, m: received.append((pid, s, m)))

    async def go():
        return g.submit("필러 cut", "1. cut\n2. cut")
    pid = _asyncio.run(go())

    # Qt direct connection — emit 은 동기적이라 호출 직후 도착.
    assert len(received) == 1
    r_pid, r_summary, r_markdown = received[0]
    assert r_pid == pid
    assert r_summary == "필러 cut"
    assert r_markdown == "1. cut\n2. cut"


# ============================================================
# AgentRuntime 연결 — send/cancel/clear 시 cancel_all + invalidate
# ============================================================
def test_agent_runtime_creates_plan_gate(qtbot) -> None:
    """AgentRuntime 이 VideoTools 의 PlanGate 인스턴스를 사용."""
    from screen_recorder.agent.runtime import AgentRuntime
    from screen_recorder.agent.tools import VideoTools

    class _Stub:
        def has_active_video(self): return False

    vt = VideoTools(adapter=_Stub())
    rt = AgentRuntime(video_tools=vt)
    # PlanGate 가 VideoTools 와 AgentRuntime 모두에서 동일 인스턴스여야.
    assert rt.plan_gate() is vt.plan_gate()


def test_agent_runtime_invalidates_approval_on_outgoing_hook(qtbot) -> None:
    """_on_user_message_outgoing 가 cancel_all + invalidate_approval.

    asyncio worker 시작 X — invalidate 동작만 검증.
    """
    import asyncio as _asyncio
    from screen_recorder.agent.runtime import AgentRuntime
    from screen_recorder.agent.tools import VideoTools

    class _Stub:
        def has_active_video(self): return False

    vt = VideoTools(adapter=_Stub())
    rt = AgentRuntime(video_tools=vt)
    g = rt.plan_gate()

    async def setup():
        pid = g.submit("s", "m")
        g.approve(pid)
    _asyncio.run(setup())

    g.require_approval()   # OK.

    rt._on_user_message_outgoing()

    with pytest.raises(ValueError):
        g.require_approval()
