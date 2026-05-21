"""TransformersBackend — Qwen2.5-Omni 시리즈 (transformers + bitsandbytes).

ChatBackend Protocol 구현. ClaudeBackend 와 같은 emit_fn 콜백 패턴 — AgentMessage /
AgentEvent 발행. Qt 의존 없음.

스레드 모델: 호출자 (runtime.py 의 worker thread) 가 자체 asyncio loop 위에서 이
메서드들을 await. transformers.generate() 는 blocking + GIL 보유 — asyncio loop
블록 방지를 위해 별도 thread (asyncio.to_thread) 에서 실행.

수명주기:
- start_session(): 옵션 저장만. 모델 로드는 lazy (첫 send_message).
- send_message(): 모델 로드 → conversation 빌드 → generate → emit. (Task 3-5)
- cancel(): stop_flag set → generate 의 StoppingCriteria 가 다음 토큰에서 멈춤. (Task 5-6)
- close(): 모델 unload + gc.collect() — VRAM 회수.

현 sub-plan: text + image 만. audio/video 는 sub-plan 7.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from .base import AgentEvent, AgentMessage, ChatInput, EmitFn


_log = logging.getLogger(__name__)


class TransformersBackend:
    """transformers 기반 백엔드. 현 PoC: Qwen2.5-Omni 7B text + image."""

    def __init__(self, repo_id: str) -> None:
        self._repo_id = repo_id
        self._system_prompt: str = ""
        self._model: Optional[Any] = None
        self._processor: Optional[Any] = None
        self._stop_flag: Optional[threading.Event] = None

    async def start_session(
        self, system_prompt: str, tools: dict[str, Any], model: str,
    ) -> None:
        """옵션 저장만 — 모델 로드는 lazy (첫 send_message).

        tools: 현 sub-plan 에선 무시 (sub-plan 6 의 tool_adapter 에서 사용).
        model: ModelRegistry 의 id (sub-plan 3) — 현 PoC 는 1개 모델 hardcoded.
        """
        self._system_prompt = system_prompt

    async def close(self) -> None:
        """모델 unload + gc — VRAM 회수."""
        self._model = None
        self._processor = None
        gc.collect()

    async def cancel(self) -> None:
        """진행 중 generate 의 stop_flag set — 다음 토큰에서 멈춤."""
        flag = self._stop_flag
        if flag is not None:
            flag.set()

    def supports_modality(self, modality: str) -> bool:
        # sub-plan 2: text + image 만. audio/video 는 sub-plan 7.
        return modality == "image"

    async def send_message(self, msg: ChatInput, emit_fn: EmitFn) -> None:
        """Task 3-5 에서 채워짐."""
        raise NotImplementedError

    async def send_tool_result(
        self, tool_use_id: str, result: Any, emit_fn: EmitFn,
    ) -> None:
        """sub-plan 6 까지 no-op stub."""
        _log.debug("send_tool_result called (no-op for PoC): tool_use_id=%s", tool_use_id)

    async def _ensure_model_loaded(self) -> None:
        """첫 호출 시 transformers import + 모델 로드. 이후 호출은 캐싱."""
        if self._model is not None and self._processor is not None:
            return
        from transformers import (
            Qwen2_5OmniForConditionalGeneration,
            Qwen2_5OmniProcessor,
        )
        self._model = await asyncio.to_thread(
            Qwen2_5OmniForConditionalGeneration.from_pretrained,
            self._repo_id,
            torch_dtype="auto",
            device_map="auto",
        )
        self._processor = await asyncio.to_thread(
            Qwen2_5OmniProcessor.from_pretrained,
            self._repo_id,
        )
