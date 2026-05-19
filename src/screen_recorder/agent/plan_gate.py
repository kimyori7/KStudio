"""Plan-Gate — Claude 의 편집 의도를 사용자에게 ✓/✗ 받는 게이트.

worker(asyncio) ↔ UI(Qt) future bridge:
- worker: submit() → plan_id, await_decision(pid) → PlanDecision
- UI: approve(pid) / reject(pid, reason) / cancel_all()

승인 상태: last_approved_plan_id 가 set 되어 있으면 propose_* 통과.
새 사용자 메시지가 들어오면 invalidate_approval() — 다음 propose 는 새 plan 필요.

Phase 1 (이 파일): 순수 도메인 로직. Qt Signal 통합은 다음 task 에서.
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass


@dataclass
class PlanDecision:
    """사용자의 plan 결정."""
    approved: bool
    reason: str = ""   # reject 시 사용자 입력 (빈 문자열 허용)


class PlanGate:
    """worker ↔ UI bridge + 승인 상태."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # plan_id → (loop, asyncio.Future). loop 는 await_decision 호출한 loop.
        self._pending: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Future]] = {}
        self._last_approved_plan_id: str | None = None

    # ---------- worker side ----------
    def submit(self, summary: str, markdown: str) -> str:
        """worker 측. plan_id 발급. (UI 시그널 emit 은 다음 task — 여기선 등록만.)"""
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        return plan_id

    async def await_decision(self, plan_id: str) -> PlanDecision:
        """worker 측. 사용자 결정까지 await.

        Future 가 cancel_all / approve / reject 중 하나로 해결됨.
        같은 plan_id 가 await_decision 호출 *직후* 에 등록 — UI 가 그 사이에 resolve
        호출해도 lock 으로 race 차단.
        """
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        with self._lock:
            self._pending[plan_id] = (loop, fut)
        return await fut

    def require_approval(self) -> None:
        """propose_* 도구 시작에서 호출. 승인 없으면 ValueError.

        에러 메시지는 Claude 의 자기 교정 유도 문구 — 도구 응답에서 그대로 노출.
        """
        with self._lock:
            if self._last_approved_plan_id is None:
                raise ValueError(
                    "이 도구 호출 전에 submit_plan 으로 plan 을 제출하고 "
                    "사용자 ✓ 를 받아야 합니다. submit_plan 부터 호출하세요."
                )

    # ---------- UI side ----------
    def approve(self, plan_id: str) -> None:
        """UI 측. last_approved_plan_id 설정 + 해당 future approved=True."""
        with self._lock:
            self._last_approved_plan_id = plan_id
            entry = self._pending.pop(plan_id, None)
        if entry is None:
            return   # unknown plan_id — race 방어.
        loop, fut = entry
        self._resolve(loop, fut, PlanDecision(approved=True, reason=""))

    def reject(self, plan_id: str, reason: str) -> None:
        """UI 측. future approved=False, reason 전달. last_approved 변경 X."""
        with self._lock:
            entry = self._pending.pop(plan_id, None)
        if entry is None:
            return
        loop, fut = entry
        self._resolve(loop, fut, PlanDecision(approved=False, reason=reason))

    def cancel_all(self) -> None:
        """앱 종료 / Claude cancel / 새 사용자 메시지. 모든 pending reject."""
        with self._lock:
            entries = list(self._pending.values())
            self._pending.clear()
        for loop, fut in entries:
            self._resolve(loop, fut, PlanDecision(approved=False, reason="cancelled"))

    def invalidate_approval(self) -> None:
        """새 사용자 메시지 도착 시 호출. last_approved_plan_id None 으로."""
        with self._lock:
            self._last_approved_plan_id = None

    # ---------- internal ----------
    @staticmethod
    def _resolve(
        loop: asyncio.AbstractEventLoop,
        fut: asyncio.Future,
        decision: PlanDecision,
    ) -> None:
        """asyncio.Future 는 loop 의 thread 에서만 set 가능 → call_soon_threadsafe."""
        def _set():
            if not fut.done():
                fut.set_result(decision)
        loop.call_soon_threadsafe(_set)
