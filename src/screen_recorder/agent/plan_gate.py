"""Plan-Gate — Claude 의 편집 의도를 사용자에게 ✓/✗ 받는 게이트.

worker(asyncio) ↔ UI(Qt) future bridge:
- worker: submit() → plan_id, await_decision(pid) → PlanDecision
- UI: approve(pid) / reject(pid, reason) / cancel_all()

승인 상태: last_approved_plan_id 가 set 되어 있으면 propose_* 통과.
새 사용자 메시지가 들어오면 invalidate_approval() — 다음 propose 는 새 plan 필요.

Phase 3 (이 파일): QObject 로 전환 + plan_submitted Signal 추가.
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class PlanDecision:
    """사용자의 plan 결정."""
    approved: bool
    reason: str = ""   # reject 시 사용자 입력 (빈 문자열 허용)


class PlanGate(QObject):
    """worker ↔ UI bridge + 승인 상태."""

    # UI 가 PlanCard 생성하는 트리거 — (plan_id, summary, markdown).
    plan_submitted = Signal(str, str, str)
    # UI 가 기존 PlanCard 상태 갱신하는 트리거 — (plan_id, outcome).
    # outcome: 'approved' / 'rejected' / 'cancelled'.
    # cancel_all 이 외부에서 발생할 때 stale card 의 ✓/✗ 버튼을 비활성화하려면 필요.
    plan_resolved = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        # plan_id → (loop, asyncio.Future). loop 는 await_decision 호출한 loop.
        self._pending: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Future]] = {}
        # plan_id → (summary, markdown). UI 가 시각화에 사용. submit() 에서 register.
        self._submitted_meta: dict[str, tuple[str, str]] = {}
        self._last_approved_plan_id: str | None = None

    # ---------- worker side ----------
    def submit(self, summary: str, markdown: str) -> str:
        """worker 측. plan_id 발급 + future 등록 (race-free) + UI Signal emit.

        호출자는 worker 의 asyncio loop 안에 있어야 — submit_plan tool handler 의 async def
        안에서 호출되므로 get_running_loop() 가 항상 성공. UI 가 submit 직후 approve 해도
        이미 등록된 future 가 받아 resolve.
        """
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        with self._lock:
            self._pending[plan_id] = (loop, fut)
            self._submitted_meta[plan_id] = (summary, markdown)
        # UI 스레드로 자동 큐잉 (QueuedConnection — worker→UI 크로스 스레드).
        # Direct connection (same thread) 면 동기적으로 슬롯 실행.
        self.plan_submitted.emit(plan_id, summary, markdown)
        return plan_id

    async def await_decision(self, plan_id: str) -> PlanDecision:
        """worker 측. submit() 에서 등록한 future 를 await.

        submit/await_decision 사이 race 는 submit() 의 등록 시점에 해결 — 여기선 단순 lookup.
        """
        with self._lock:
            entry = self._pending.get(plan_id)
        if entry is None:
            raise ValueError(
                f"plan_id={plan_id!r} not registered — submit() 부터 호출해야 합니다."
            )
        _loop, fut = entry
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
            entry = self._pending.pop(plan_id, None)
            if entry is not None:
                self._last_approved_plan_id = plan_id
                self._submitted_meta.pop(plan_id, None)
        if entry is None:
            return   # unknown plan_id — race 방어.
        loop, fut = entry
        self._resolve(loop, fut, PlanDecision(approved=True, reason=""))
        self.plan_resolved.emit(plan_id, "approved")

    def reject(self, plan_id: str, reason: str) -> None:
        """UI 측. future approved=False, reason 전달. last_approved 변경 X."""
        with self._lock:
            entry = self._pending.pop(plan_id, None)
            self._submitted_meta.pop(plan_id, None)
        if entry is None:
            return
        loop, fut = entry
        self._resolve(loop, fut, PlanDecision(approved=False, reason=reason))
        self.plan_resolved.emit(plan_id, "rejected")

    def cancel_all(self) -> None:
        """앱 종료 / Claude cancel / 새 사용자 메시지. 모든 pending reject.

        UI 의 stale PlanCard 들이 'cancelled' 표시로 잠기도록 각 plan_id 에 대해
        plan_resolved emit — _on_user_message_outgoing 흐름 (Task 3) 에서 호출 시
        화면에 남은 카드들이 '취소됨' 으로 갱신.
        """
        with self._lock:
            ids_entries = list(self._pending.items())
            self._pending.clear()
            self._submitted_meta.clear()
        for plan_id, (loop, fut) in ids_entries:
            self._resolve(loop, fut, PlanDecision(approved=False, reason="cancelled"))
            self.plan_resolved.emit(plan_id, "cancelled")

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
        """asyncio.Future 는 loop 의 thread 에서만 set 가능 → call_soon_threadsafe.

        loop 가 닫혀 있으면 (테스트 teardown(asyncio.run) 또는 앱 종료 시) 명시적으로
        is_closed() 가드로 skip — 상태 갱신은 이미 lock 안에서 완료됐으므로 future
        resolution 실패는 기능에 영향 없음. bare except 보다 semantic 이 명확하고
        무관한 RuntimeError 를 가리지 않음.
        """
        if loop.is_closed():
            return
        def _set():
            if not fut.done():
                fut.set_result(decision)
        loop.call_soon_threadsafe(_set)
