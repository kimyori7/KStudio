"""ChatBackend Protocol 정의.

기존 AgentMessage/AgentEvent (runtime.py) 를 그대로 사용 — 정규화된 이벤트 역할 이미
함. 새 타입 추가 안 함 (YAGNI). 백엔드는 emit_fn 콜백으로 이벤트 발행.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol


# emit 콜백 — runtime.py 의 Qt Signal emit 으로 연결됨.
# msg: AgentMessage / event: AgentEvent (runtime.py 정의)
EmitFn = Callable[[Any], None]


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
        tools: dict,
        model: str,
    ) -> None: ...

    async def send_message(self, msg: ChatInput, emit_fn: EmitFn) -> None: ...

    async def send_tool_result(
        self, tool_use_id: str, result: Any, emit_fn: EmitFn,
    ) -> None: ...

    async def cancel(self) -> None: ...

    async def close(self) -> None: ...

    def supports_modality(self, modality: str) -> bool:
        """'image' / 'audio' / 'video' — 백엔드가 이 modality 입력 받는지."""
        ...
