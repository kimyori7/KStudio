"""Claude Agent in-app — 채팅 패널에서 영상 편집을 자율화하기 위한 에이전트 SDK 임베드.

Phase A (2026-05-13): read-only 비디오 상태 도구 5개 + 채팅 패널 + SDK 런타임.

레이어:
- `tools_video` — Claude 가 호출하는 비디오 상태 조회 도구 (get_*).
- `runtime`    — Claude Agent SDK 클라이언트 래퍼 + Qt 시그널 어댑터.
- `proposals`  — Phase B 대비 placeholder (편집 제안 큐).

설계 원칙: 직접 mutation 금지. 향후 편집 도구는 `propose_*` 접두사로 큐에만 쌓고
사용자가 명시적으로 commit_proposals() 호출 시에만 sidecar 에 반영.
"""
from .runtime import AgentRuntime, AgentMessage, AgentEvent
from .tools_video import VideoTools, VideoSessionAdapter
from .proposals import EffectProposal, ProposalQueue, build_effect_from_proposal

__all__ = [
    "AgentRuntime", "AgentMessage", "AgentEvent",
    "VideoTools", "VideoSessionAdapter",
    "EffectProposal", "ProposalQueue", "build_effect_from_proposal",
]
