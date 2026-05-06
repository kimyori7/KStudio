"""진동벨(request_id) 패턴 — 오래 걸리는 도구의 비동기 결과 보관소.

영역 캡처처럼 사용자 액션을 기다리는 도구나 AI 업스케일처럼 수십 초 걸리는
도구는 LLM 의 도구 호출 timeout(보통 30~60초) 을 넘길 수 있다. 이런 도구는:

1. 즉시 `request_id` 를 반환 (`status: "pending"`)
2. LLM 이 `get_request_status(request_id)` 로 폴링
3. 완료되면 결과/실패 dict 반환

`PendingRequestStore` 는 main_window 가 보유 (UI 스레드) — 도구 핸들러가 직접
읽고 쓴다. 외부 동시성은 없으므로 락은 불필요.
"""
from __future__ import annotations
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class PendingRequest:
    request_id: str
    tool: str
    status: str = "pending"   # "pending" | "done" | "failed" | "cancelled"
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "tool": self.tool,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
        }


class PendingRequestStore:
    """진동벨 보관소. 메모리에만 — KStudio 재시작하면 비워진다 (LLM 도 새로 시작)."""

    def __init__(self) -> None:
        self._requests: dict[str, PendingRequest] = {}

    def create(self, tool: str) -> str:
        """새 진동벨 발급 — 8바이트 URL-safe 토큰. 호출자에게 request_id 반환."""
        rid = secrets.token_urlsafe(8)
        self._requests[rid] = PendingRequest(request_id=rid, tool=tool)
        return rid

    def complete(self, rid: str, result: dict) -> None:
        req = self._requests.get(rid)
        if req is None or req.status != "pending":
            return
        req.status = "done"
        req.result = result
        req.completed_at = datetime.now()

    def fail(self, rid: str, error: str) -> None:
        req = self._requests.get(rid)
        if req is None or req.status != "pending":
            return
        req.status = "failed"
        req.error = error
        req.completed_at = datetime.now()

    def cancel(self, rid: str) -> None:
        req = self._requests.get(rid)
        if req is None or req.status != "pending":
            return
        req.status = "cancelled"
        req.completed_at = datetime.now()

    def get(self, rid: str) -> Optional[PendingRequest]:
        return self._requests.get(rid)

    def cleanup_old(self, keep_minutes: int = 30) -> None:
        """완료/실패/취소된 항목 중 keep_minutes 이상 지난 것 정리.

        진행 중(pending) 항목은 사용자가 영역 선택을 1시간 만에 끝낼 수도 있어
        절대 자동 정리 X.
        """
        cutoff = datetime.now() - timedelta(minutes=keep_minutes)
        to_remove = [
            rid for rid, req in self._requests.items()
            if req.completed_at is not None and req.completed_at < cutoff
        ]
        for rid in to_remove:
            del self._requests[rid]
