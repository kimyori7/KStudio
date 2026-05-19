"""Claude Agent 도구 surface — VideoTools 파사드.

레이어 분리:
- `_response`  — MCP 응답 빌더 (_text_result / _image_result / _error_result).
- `_format`    — 사람 읽을 수 있는 요약 + ms 포매팅 + 효과/세그먼트 summary dict.
- `read`       — 읽기 전용 도구 5개 (get_video_state, get_sidecar_summary, etc.).
- `visual`     — 비주얼 도구 2개 (get_frame_at, get_timeline_strip).
- `mutation`   — 편집 제안 도구 6개 (propose_effect 추가/삭제/수정 + list/apply/discard).

VideoTools 파사드가 세 그룹을 합쳐 mcp_server() 와 tool_names() 노출.
"""
from __future__ import annotations

import concurrent.futures
from typing import Callable, Optional

from claude_agent_sdk import create_sdk_mcp_server

from ..adapter import VideoSessionAdapter
from ..plan_gate import PlanGate
from ..proposals import EffectProposal, ProposalQueue
from .mutation import make_mutation_tools, MUTATION_TOOL_NAMES
from .preview import make_preview_tools, PREVIEW_TOOL_NAMES
from .read import make_read_tools, READ_TOOL_NAMES
from .transcript import (
    TRANSCRIPT_TOOL_NAMES, DownloadCallback,
    TranscriptContext, make_transcript_tools,
)
from .visual import make_visual_tools, VISUAL_TOOL_NAMES


# Phase B mutation 도구 — UI 측 콜백 시그니처.
ApplyCallback = Callable[[list[EffectProposal], concurrent.futures.Future], None]

_MCP_SERVER_NAME = "kstudio_video"


class VideoTools:
    """SDK 도구 모음 파사드. mcp_server() / tool_names() 노출.

    `adapter`        : VideoSessionAdapter 구현체.
    `ffmpeg_path`    : 비주얼 도구가 사용. None 이면 비주얼 도구는 호출 시 에러.
    `proposal_queue` : Phase B mutation 도구 공유 큐. None 이면 새로 생성.
    `on_apply`       : Phase B apply_proposals 가 UI 스레드 마샬링용으로 호출.
    """

    def __init__(
        self,
        adapter: VideoSessionAdapter,
        ffmpeg_path: Optional[str] = None,
        proposal_queue: Optional[ProposalQueue] = None,
        on_apply: Optional[ApplyCallback] = None,
        transcript_ctx: Optional[TranscriptContext] = None,
        on_download_whisper: Optional[DownloadCallback] = None,
        plan_gate: Optional[PlanGate] = None,
    ) -> None:
        self._adapter = adapter
        self._ffmpeg_path = ffmpeg_path
        self._queue = proposal_queue or ProposalQueue()
        self._on_apply = on_apply
        self._transcript_ctx = transcript_ctx
        self._on_download_whisper = on_download_whisper
        self._plan_gate = plan_gate or PlanGate()

    def proposal_queue(self) -> ProposalQueue:
        return self._queue

    def plan_gate(self) -> PlanGate:
        return self._plan_gate

    def mcp_server(self):
        """SDK 가 인식하는 in-process MCP 서버. ClaudeAgentOptions.mcp_servers 에 등록."""
        tools = (
            make_read_tools(self._adapter)
            + make_visual_tools(self._adapter, self._ffmpeg_path)
            + make_mutation_tools(self._adapter, self._queue, self._on_apply, self._plan_gate)
            + make_preview_tools(self._adapter, self._queue, self._ffmpeg_path)
        )
        if self._transcript_ctx is not None:
            tools = tools + make_transcript_tools(
                self._adapter, self._transcript_ctx,
                on_download=self._on_download_whisper,
            )
        return create_sdk_mcp_server(
            name=_MCP_SERVER_NAME, version="0.1.0", tools=tools,
        )

    def tool_names(self) -> list[str]:
        """allowed_tools 에 넘길 prefix 붙은 tool key 목록."""
        prefix = f"mcp__{_MCP_SERVER_NAME}__"
        base = (
            *READ_TOOL_NAMES, *VISUAL_TOOL_NAMES,
            *MUTATION_TOOL_NAMES, *PREVIEW_TOOL_NAMES,
        )
        if self._transcript_ctx is not None:
            base = (*base, *TRANSCRIPT_TOOL_NAMES)
        return [prefix + name for name in base]


__all__ = [
    "VideoTools",
    "VideoSessionAdapter",
    "ApplyCallback",
    "TranscriptContext",
]
