"""PlanGate — worker↔UI bridge + 승인 상태 관리.

Phase 1 (이 파일): 순수 도메인 로직 (Qt Signal 없이).
"""
from __future__ import annotations

import asyncio
import threading
import pytest

from screen_recorder.agent.plan_gate import PlanGate, PlanDecision


def test_submit_returns_unique_plan_id() -> None:
    g = PlanGate()
    pid1 = g.submit("summary1", "markdown1")
    pid2 = g.submit("summary2", "markdown2")
    assert pid1 != pid2
    assert pid1.startswith("plan_")
    assert pid2.startswith("plan_")


def test_approve_resolves_future_with_approved_true() -> None:
    """submit → 별도 스레드에서 approve → await_decision 이 approved=True 반환."""
    g = PlanGate()
    pid = g.submit("s", "m")

    async def waiter():
        return await g.await_decision(pid)

    loop = asyncio.new_event_loop()
    try:
        # approve 는 별도 스레드에서 (UI 시뮬레이션) — loop run 시작 후 잠깐 뒤.
        def approve_later():
            import time
            time.sleep(0.05)
            g.approve(pid)
        threading.Thread(target=approve_later).start()
        decision = loop.run_until_complete(waiter())
    finally:
        loop.close()

    assert decision.approved is True
    assert decision.reason == ""


def test_reject_resolves_future_with_reason() -> None:
    g = PlanGate()
    pid = g.submit("s", "m")

    async def waiter():
        return await g.await_decision(pid)

    loop = asyncio.new_event_loop()
    try:
        def reject_later():
            import time
            time.sleep(0.05)
            g.reject(pid, "이건 아니야")
        threading.Thread(target=reject_later).start()
        decision = loop.run_until_complete(waiter())
    finally:
        loop.close()

    assert decision.approved is False
    assert decision.reason == "이건 아니야"


def test_cancel_all_rejects_pending_with_cancelled_reason() -> None:
    g = PlanGate()
    pid = g.submit("s", "m")

    async def waiter():
        return await g.await_decision(pid)

    loop = asyncio.new_event_loop()
    try:
        def cancel_later():
            import time
            time.sleep(0.05)
            g.cancel_all()
        threading.Thread(target=cancel_later).start()
        decision = loop.run_until_complete(waiter())
    finally:
        loop.close()

    assert decision.approved is False
    assert decision.reason == "cancelled"


def test_require_approval_raises_when_no_approval() -> None:
    g = PlanGate()
    with pytest.raises(ValueError) as exc:
        g.require_approval()
    assert "submit_plan" in str(exc.value)


def test_require_approval_passes_after_approve() -> None:
    g = PlanGate()
    pid = g.submit("s", "m")
    g.approve(pid)
    # require_approval 이 예외 안 던지면 통과.
    g.require_approval()


def test_invalidate_approval_makes_require_fail_again() -> None:
    g = PlanGate()
    pid = g.submit("s", "m")
    g.approve(pid)
    g.require_approval()   # OK.
    g.invalidate_approval()
    with pytest.raises(ValueError):
        g.require_approval()


def test_reject_does_not_change_last_approved() -> None:
    """reject 는 단지 future 만 해결 — 이전 approval 무효화 X."""
    g = PlanGate()
    pid1 = g.submit("s1", "m1")
    g.approve(pid1)
    pid2 = g.submit("s2", "m2")
    g.reject(pid2, "no")
    # 첫 plan 의 승인은 여전히 유효해야 함 — propose_* 통과 가능.
    g.require_approval()


def test_two_plans_independent_decisions() -> None:
    """동시 2 plan — 각각 별도 future 해결."""
    g = PlanGate()
    pid1 = g.submit("s1", "m1")
    pid2 = g.submit("s2", "m2")

    async def both():
        results = await asyncio.gather(
            g.await_decision(pid1), g.await_decision(pid2)
        )
        return results

    loop = asyncio.new_event_loop()
    try:
        def resolve_both():
            import time
            time.sleep(0.05)
            g.approve(pid1)
            g.reject(pid2, "two")
        threading.Thread(target=resolve_both).start()
        r1, r2 = loop.run_until_complete(both())
    finally:
        loop.close()

    assert r1.approved is True
    assert r2.approved is False and r2.reason == "two"


def test_approve_unknown_plan_id_is_noop() -> None:
    """존재하지 않는 plan_id 로 approve → 조용히 무시 (race condition 방어)."""
    g = PlanGate()
    g.approve("plan_nonexistent")   # 예외 X.


def test_reject_unknown_plan_id_is_noop() -> None:
    g = PlanGate()
    g.reject("plan_nonexistent", "")   # 예외 X.
