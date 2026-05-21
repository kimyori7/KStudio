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


# Streaming sentinel — executor 에서 StopIteration 잡고 이걸 반환해서
# 메인 코루틴에서 단순 비교 (is _STREAM_SENTINEL) 로 종료 판정.
_STREAM_SENTINEL = object()


def _next_or_sentinel(it):
    """next(it) — StopIteration 시 sentinel 반환 (executor 에서 예외 처리 단순화)."""
    try:
        return next(it)
    except StopIteration:
        return _STREAM_SENTINEL


class TransformersBackend:
    """transformers 기반 백엔드. 현 PoC: Qwen2.5-Omni 7B text + image."""

    def __init__(self, repo_id: str) -> None:
        self._repo_id = repo_id
        self._system_prompt: str = ""
        self._model: Optional[Any] = None
        self._processor: Optional[Any] = None
        self._stop_flag: Optional[threading.Event] = None
        # 임시 파일 정리 추적 — 매 send_message finally 에서 unlink.
        self._temp_files: list[Path] = []

    async def start_session(
        self, system_prompt: str, tools: dict[str, Any], model: str,
    ) -> None:
        """옵션 저장만 — 모델 로드는 lazy (첫 send_message).

        tools: 현 sub-plan 에선 무시 (sub-plan 6 의 tool_adapter 에서 사용).
        model: ModelRegistry 의 id (sub-plan 3) — 현 PoC 는 1개 모델 hardcoded.
        """
        self._system_prompt = system_prompt

    def _build_conversation(self, msg: ChatInput) -> list[dict]:
        """ChatInput → Qwen2.5-Omni conversation list (HF 모델카드 형식 정확히 따름).

        text-only: user content = string.
        with images: user content = list of {"type":"image","image":path} +
                     {"type":"text","text":...}. PNG bytes 는 임시 파일로 저장 후
                     path 사용 — Qwen processor 가 path 만 받음 (bytes 미지원).

        임시 파일은 self._temp_files 에 추적 — send_message finally 에서 정리.
        audio/video 는 sub-plan 7 — 현 단계는 무시.
        """
        import tempfile
        conv: list[dict] = [
            {"role": "system",
             "content": [{"type": "text", "text": self._system_prompt}]},
        ]
        if msg.images:
            content_blocks: list[dict] = []
            for img_bytes in msg.images:
                # delete=False — close 후에도 파일 살아 있음. 우리가 unlink.
                tf = tempfile.NamedTemporaryFile(
                    suffix=".png", delete=False, mode="wb",
                )
                tf.write(img_bytes)
                tf.close()
                path = Path(tf.name)
                self._temp_files.append(path)
                content_blocks.append({"type": "image", "image": str(path)})
            content_blocks.append({
                "type": "text",
                "text": msg.text or "(첨부 이미지)",
            })
            conv.append({"role": "user", "content": content_blocks})
        else:
            conv.append({"role": "user", "content": msg.text})
        return conv

    def _cleanup_temp_files(self) -> None:
        """send_message finally — 추적된 temp 파일 모두 unlink."""
        for p in self._temp_files:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                _log.exception("TransformersBackend: temp 파일 정리 실패 %s", p)
        self._temp_files.clear()

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
        """텍스트/이미지 메시지 처리 — TextIteratorStreamer 로 token streaming.

        흐름:
        1. 모델 로드 + conversation 빌드 + processor inputs.
        2. TextIteratorStreamer 생성 (skip_prompt=True — 입력 토큰 제외).
        3. generate 를 별도 thread 에서 실행 (blocking + GIL).
        4. streamer iterate → chunk 마다 AgentMessage emit (loop.run_in_executor 로
           한 chunk 씩 받음 — asyncio loop 블록 안 함).
        5. thread join + done emit.

        에러는 emit_fn(AgentEvent(kind='error', ...)) 로만 전달.
        """
        try:
            await self._ensure_model_loaded()
            emit_fn(AgentEvent(kind="started"))

            from transformers import TextIteratorStreamer
            from qwen_omni_utils import process_mm_info

            conversation = self._build_conversation(msg)
            text = self._processor.apply_chat_template(
                conversation, add_generation_prompt=True, tokenize=False,
            )
            audios, images, videos = process_mm_info(
                conversation, use_audio_in_video=False,
            )
            inputs = self._processor(
                text=text,
                audio=audios, images=images, videos=videos,
                return_tensors="pt", padding=True,
                use_audio_in_video=False,
            )
            inputs = inputs.to(self._model.device).to(self._model.dtype)

            streamer = TextIteratorStreamer(
                self._processor,
                skip_prompt=True,
                skip_special_tokens=True,
            )
            self._stop_flag = threading.Event()
            stopping = self._make_stopping_criteria(self._stop_flag)

            gen_kwargs = dict(
                **inputs,
                streamer=streamer,
                return_audio=False,
                use_audio_in_video=False,
                stopping_criteria=stopping,
                # 무한 generate 방지 — 기본값(8192 등)이 너무 커서 모델이 끝없이 생성.
                # 512 면 한국어 ~700자 = 일반 답변 충분. 코드 같이 긴 응답 필요 시 후속 조정.
                max_new_tokens=512,
                # greedy 대신 약한 sampling — 약간 빠르고 자연스러움.
                do_sample=False,
            )

            # generate thread 안에서 raise 된 예외는 main coroutine 에 자동
            # 전파되지 않음 → 박스에 담아 두고 thread.join 후 재발생시켜 외부
            # except 블록에서 error event emit.
            gen_error: dict[str, BaseException] = {}

            def _run_generate():
                try:
                    self._model.generate(**gen_kwargs)
                except BaseException as e:  # noqa: BLE001 — propagate to main
                    _log.exception("TransformersBackend: generate thread 실패")
                    gen_error["exc"] = e
                    streamer.end()   # iterate 풀어주기

            thread = threading.Thread(target=_run_generate, daemon=True)
            thread.start()

            # streamer iterate — blocking. loop.run_in_executor 로 한 chunk 씩.
            loop = asyncio.get_running_loop()
            iter_streamer = iter(streamer)
            while True:
                chunk = await loop.run_in_executor(None, _next_or_sentinel, iter_streamer)
                if chunk is _STREAM_SENTINEL:
                    break
                if chunk:
                    emit_fn(AgentMessage(role="assistant", text=chunk))

            await asyncio.to_thread(thread.join)
            if "exc" in gen_error:
                raise gen_error["exc"]
            emit_fn(AgentEvent(kind="done"))
        except Exception as exc:
            _log.exception("TransformersBackend: send_message 실패")
            emit_fn(AgentEvent(kind="error", detail=str(exc)))
        finally:
            self._stop_flag = None
            self._cleanup_temp_files()

    def _make_stopping_criteria(self, flag: threading.Event):
        """flag 가 set 되면 stop. cancel() 진입점.

        Task 6 에서 실제 cancel 흐름 검증.
        """
        from transformers import StoppingCriteria, StoppingCriteriaList

        class _StopOnFlag(StoppingCriteria):
            def __init__(self, flag): self.flag = flag
            def __call__(self, input_ids, scores, **kwargs) -> bool:
                return self.flag.is_set()

        return StoppingCriteriaList([_StopOnFlag(flag)])

    async def send_tool_result(
        self, tool_use_id: str, result: Any, emit_fn: EmitFn,
    ) -> None:
        """sub-plan 6 까지 no-op stub."""
        _log.debug("send_tool_result called (no-op for PoC): tool_use_id=%s", tool_use_id)

    async def _ensure_model_loaded(self) -> None:
        """첫 호출 시 transformers import + 모델 로드. 이후 호출은 캐싱.

        속도/메모리 최적화:
        - attn_implementation="sdpa" — PyTorch built-in scaled_dot_product_attention.
          기본 eager 보다 2-3배 빠름. flash-attn 별도 설치 없이 즉시 적용.
        - 모델 로드 후 disable_talker() — Qwen2.5-Omni 의 speech 생성 모듈 (~2GB
          VRAM) 해제. text/image 만 쓰므로 불필요.
        """
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
            attn_implementation="sdpa",
        )
        # text 응답만 사용 — speech 생성 모듈 해제 (메모리 ~2GB + 약간 빠름).
        try:
            disable = getattr(self._model, "disable_talker", None)
            if callable(disable):
                disable()
        except Exception:
            _log.exception("disable_talker 실패 (무시 — talker 활성 상태 유지)")
        self._processor = await asyncio.to_thread(
            Qwen2_5OmniProcessor.from_pretrained,
            self._repo_id,
        )
