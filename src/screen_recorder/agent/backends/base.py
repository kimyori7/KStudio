"""ChatBackend Protocol + 정규화된 이벤트 dataclass.

AgentMessage / AgentEvent 는 모든 백엔드가 공통으로 emit 하는 타입 — 백엔드별
SDK 차이를 흡수해서 UI 가 동일한 형태로 받음. (Sub-plan 1 까지는 runtime.py 에
있었지만 sub-plan 2 의 두 번째 백엔드 (transformers) 가 같은 타입 emit 해야 하므로
backends/base.py 로 이전. runtime.py 는 외부 호환 위해 re-export 만 유지.)

EmitFn 은 backend → UI 콜백 — runtime.py 의 Qt Signal emit 에 연결됨. Qt 의존 없음.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol


@dataclass
class AgentMessage:
    """채팅 패널이 표시하는 한 줄.

    role: user / assistant / thinking / system / tool_use / tool_result / error / proposals_preview
    image_bytes / image_mime: tool_result 중 이미지 (frame_at / timeline_strip) 인라인 표시용.
    proposals: proposals_preview role 의 카드 표시용. 각 dict 는 action/type/payload 포함.
    """
    role: str
    text: str
    tool_name: Optional[str] = None
    image_bytes: Optional[bytes] = None
    image_mime: Optional[str] = None
    proposals: Optional[list[dict]] = None


@dataclass
class AgentEvent:
    """진행 상황 — UI 가 진행률/상태 표시할 때."""
    kind: str   # "started" / "tool_use" / "tool_result" / "done" / "error"
    detail: str = ""


# emit 콜백 — runtime.py 의 Qt Signal emit 으로 연결됨.
EmitFn = Callable[[Any], None]   # 실제로는 Callable[[AgentMessage | AgentEvent], None]


@dataclass
class ChatInput:
    """사용자 → 백엔드 메시지. 텍스트 + 선택적 첨부 (이미지/오디오/영상).

    image: PNG/JPEG bytes 리스트 — Ctrl+V 로 붙여넣은 스크린샷 등.
    audio_path/video_path: 멀티모달 omni 백엔드 (Qwen 등) 에서 사용. Claude 백엔드는
    무시 (필요 시 frame extraction 으로 image 폴백 — sub-plan 7).
    """
    text: str
    images: Optional[list[bytes]] = None
    audio_path: Optional[str] = None
    video_path: Optional[str] = None


class ChatBackend(Protocol):
    """모든 백엔드가 구현하는 인터페이스.

    수명주기:
    1. start_session(system_prompt, tools, model) — 백엔드 초기화 + 첫 client 연결 준비.
    2. send_message(msg, emit_fn) async — 사용자 메시지 처리. 응답 동안 emit_fn 으로
       AgentMessage/AgentEvent 전달. 끝나면 "done" event emit.
    3. send_tool_result(tool_use_id, result, emit_fn) async — 도구 결과를 백엔드에 회신.
    4. cancel() — 진행 중 응답 취소.
    5. close() — 백엔드 해제 (session 종료, 모델 unload 등).
    """

    async def start_session(
        self,
        system_prompt: str,
        tools: dict[str, Any],
        model: str,
    ) -> None:
        """백엔드 초기화. 첫 send_message 전에 정확히 한 번 호출.

        tools dict shape (백엔드별 — 각 백엔드는 자기 키만 꺼내고 모르는 키는 무시):
        - ClaudeBackend:
          `{"mcp_server": <MCPServer>, "allowed_tools": list[str]}`
          MCP server 인스턴스 + 허용할 도구 이름 (prefix 포함, 예 "mcp__kstudio_video__get_video_state").
        - TransformersBackend (sub-plan 2 예정):
          `{"openai_tools": list[dict], "tool_handlers": dict[str, Callable]}`
          OpenAI function calling schema list + name → 핸들러 (in-process 실행).
          tool_adapter.py 가 MCP → OpenAI 변환.
        - LlamaCppBackend (sub-plan 5 예정):
          TransformersBackend 와 동일 shape 재사용.

        빈 dict 면 도구 없는 채팅 (PoC / 테스트).
        """
        ...

    async def send_message(self, msg: ChatInput, emit_fn: EmitFn) -> None: ...

    async def send_tool_result(
        self, tool_use_id: str, result: Any, emit_fn: EmitFn,
    ) -> None: ...

    async def cancel(self) -> None: ...

    async def close(self) -> None: ...

    def supports_modality(self, modality: str) -> bool:
        """'image' / 'audio' / 'video' — 백엔드가 이 modality 입력 받는지."""
        ...
