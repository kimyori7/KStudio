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
from typing import Any, Callable, Optional

from claude_agent_sdk import create_sdk_mcp_server

from ..adapter import VideoSessionAdapter
from ..plan_gate import PlanGate
from ..proposals import EffectProposal, ProposalQueue
from .document import (
    DOCUMENT_TOOL_NAMES, DocumentEditCallback, make_document_tools,
)
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
        document_adapter: Optional[Any] = None,
        on_document_edit: Optional[DocumentEditCallback] = None,
    ) -> None:
        self._adapter = adapter
        self._ffmpeg_path = ffmpeg_path
        self._queue = proposal_queue or ProposalQueue()
        self._on_apply = on_apply
        self._transcript_ctx = transcript_ctx
        self._on_download_whisper = on_download_whisper
        self._plan_gate = plan_gate or PlanGate()
        self._document_adapter = document_adapter
        self._on_document_edit = on_document_edit

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
        if self._document_adapter is not None:
            tools = tools + make_document_tools(
                self._document_adapter, self._on_document_edit,
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
        if self._document_adapter is not None:
            base = (*base, *DOCUMENT_TOOL_NAMES)
        return [prefix + name for name in base]

    def openai_tools_and_handlers(self) -> tuple[list[dict], dict]:
        """TransformersBackend 용 — OpenAI tools schema + name → 핸들러 dict.

        mcp_server() 와 같은 `make_*_tools` list 들을 재사용하되, MCP 래핑 없이
        각 SdkMcpTool 의 .name / .input_schema / .handler 직접 추출.
        ClaudeBackend 와 같은 19개 도구 노출 — Qwen 도 동일 surface 가능.
        """
        from ..backends.tool_adapter import mcp_to_openai_tools, mcp_to_openai_name

        # mcp_server() 와 동일한 도구 리스트 빌드.
        raw_tools = (
            make_read_tools(self._adapter)
            + make_visual_tools(self._adapter, self._ffmpeg_path)
            + make_mutation_tools(self._adapter, self._queue, self._on_apply, self._plan_gate)
            + make_preview_tools(self._adapter, self._queue, self._ffmpeg_path)
        )
        if self._transcript_ctx is not None:
            raw_tools = raw_tools + make_transcript_tools(
                self._adapter, self._transcript_ctx,
                on_download=self._on_download_whisper,
            )
        if self._document_adapter is not None:
            raw_tools = raw_tools + make_document_tools(
                self._document_adapter, self._on_document_edit,
            )

        # SdkMcpTool → MCP dict 형식으로 인터미디어트 변환 후 어댑터로 OpenAI 형식 만듦.
        prefix = f"mcp__{_MCP_SERVER_NAME}__"
        mcp_dicts: list[dict] = []
        handlers: dict[str, Any] = {}
        for t in raw_tools:
            # claude_agent_sdk 의 SdkMcpTool 공통 속성.
            name = getattr(t, "name", None)
            desc = getattr(t, "description", "")
            schema = getattr(t, "input_schema", None) or {
                "type": "object", "properties": {}, "required": [],
            }
            handler = getattr(t, "handler", None)
            if name is None or handler is None:
                continue
            full_name = prefix + name if not name.startswith(prefix) else name
            mcp_dicts.append({
                "name": full_name,
                "description": desc,
                "input_schema": schema,
            })
            handlers[mcp_to_openai_name(full_name)] = handler

        return mcp_to_openai_tools(mcp_dicts), handlers


__all__ = [
    "VideoTools",
    "VideoSessionAdapter",
    "ApplyCallback",
    "TranscriptContext",
]
