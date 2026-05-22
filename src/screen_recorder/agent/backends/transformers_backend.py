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
import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from .base import AgentEvent, AgentMessage, ChatInput, EmitFn


_log = logging.getLogger(__name__)


# Streaming sentinel — executor 에서 StopIteration 잡고 이걸 반환해서
# 메인 코루틴에서 단순 비교 (is _STREAM_SENTINEL) 로 종료 판정.
_STREAM_SENTINEL = object()

# tool use 최대 라운드 — backends/tool_loop.py 의 공통 상수 재사용 (multi-backend SSOT).
# retry 분기 때문에 직접 helper 위임은 안 했지만 상수는 공유.
from .tool_loop import DEFAULT_MAX_TOOL_ROUNDS as _MAX_TOOL_ROUNDS  # noqa: E402


def _next_or_sentinel(it):
    """next(it) — StopIteration 시 sentinel 반환 (executor 에서 예외 처리 단순화)."""
    try:
        return next(it)
    except StopIteration:
        return _STREAM_SENTINEL


# Qwen 전용 system prompt — runtime.py 의 Claude SYSTEM_PROMPT (도구 호출 가정) 가
# 그대로 가면 Qwen 이 "있지도 않은 도구의 출력 형식" 을 학습 데이터에서 모방해 가짜
# JSON (예: 1234567 ms 같은 placeholder) 생성. sub-plan 6 의 tool 어댑터 전까지
# Qwen 은 도구 호출 불가 — system prompt 도 그 사실 명확히 알려야.
_QWEN_SYSTEM_PROMPT = (
    "당신은 KStudio 안에서 동작하는 한국어 AI 비서입니다.\n"
    "\n"
    "**중요 제약 — 절대 어기지 마세요**:\n"
    "1. 당신은 KStudio 의 영상 편집 도구 (get_video_state, propose_effect, "
    "get_frame_at 등) 를 *호출할 수 없습니다*. 사용자가 영상 길이, 효과, "
    "프레임 분석 같은 영상 상태 정보를 물어봐도 *직접 답할 방법이 없습니다*.\n"
    "2. 사용자가 영상 정보를 요청하면, 가상의 JSON 출력이나 예시 값 "
    "(예: `1234567 ms`, `duration_ms: ...`) 을 만들어 답하지 마세요. "
    "그건 거짓 정보입니다. 대신 솔직히 답하세요: '죄송합니다, 현재 제가 "
    "영상 분석 도구를 호출할 수 없어 영상 메타데이터를 직접 확인하지 못합니다. "
    "Claude 모델로 전환하시거나, 캡처한 이미지를 직접 채팅에 첨부해 주시면 "
    "그 이미지를 보고 답할 수 있습니다.'\n"
    "3. 사용자가 이미지를 첨부했다면, 그 이미지를 직접 보고 묘사/분석하세요. "
    "이건 당신이 잘하는 일입니다 (멀티모달).\n"
    "4. 추측하지 마세요. 모르면 모른다고 답하세요. 거짓 데이터 생성 금지.\n"
    "\n"
    "그 외 일반 대화, 코딩 도움, 글쓰기, 이미지 분석 등은 자유롭게 도와주세요."
)


class TransformersBackend:
    """transformers 기반 백엔드. 현 PoC: Qwen2.5-Omni 7B text + image."""

    def __init__(
        self,
        repo_id: str,
        modalities: "frozenset[str] | None" = None,
        load_in_4bit: bool = False,
    ) -> None:
        """repo_id + modalities + 4-bit 양자화 옵션.

        modalities=None (기본) → 하위호환: Omni 가정 (기존 동작 유지).
        text 만 있으면 text-only path (AutoModelForCausalLM + AutoTokenizer).
        image/audio/video 중 하나라도 있으면 Omni path (Qwen2_5OmniForConditionalGeneration).

        load_in_4bit=True (2026-05-22 추가) → bitsandbytes NF4 4-bit 로드. Qwen2.5-Omni 7B
        기준 VRAM ~14GB → ~7GB, 속도 1.3~1.7배 (RTX 50 series + CUDA 13 검증). 정확도
        손실 거의 없음 (NF4 + double quant + bf16 compute).
        """
        self._repo_id = repo_id
        self._modalities: frozenset = modalities if modalities is not None else frozenset({"text", "image", "audio", "video"})
        self._load_in_4bit = load_in_4bit
        self._system_prompt: str = _QWEN_SYSTEM_PROMPT
        self._model: Optional[Any] = None
        self._processor: Optional[Any] = None
        self._stop_flag: Optional[threading.Event] = None
        # 임시 파일 정리 추적 — 매 send_message finally 에서 unlink.
        self._temp_files: list[Path] = []
        # 대화 누적 — Qwen 은 SDK 가 자동 누적 안 함. 매 turn 직접 append.
        # 형식: [{"role": "user"|"assistant", "content": <str 또는 list-of-blocks>}, ...]
        # system 은 _system_prompt 로 별도 — _build_conversation 이 합쳐서 반환.
        self._history: list[dict] = []
        # Tool use — start_session 에서 채움.
        self._openai_tools: list[dict] = []
        self._tool_handlers: dict[str, Any] = {}
        self._tool_strategy: str = "none"

    def _is_text_only(self) -> bool:
        """text 만 지원하는 모델 (Qwen2.5-7B-Instruct 등) → AutoModel/AutoTokenizer 경로."""
        return self._modalities == frozenset({"text"})

    async def start_session(
        self, system_prompt: str, tools: dict[str, Any], model: str,
    ) -> None:
        """세션 초기화 — 호출자(runtime.py) 의 system_prompt 는 *무시* 하고
        TransformersBackend 전용 prompt 사용. 이유는 _QWEN_SYSTEM_PROMPT docstring.

        history 초기화 — 새 session 시작.

        tools dict:
        - "openai_tools": list[dict] — OpenAI function calling schema (mcp_to_openai_tools 결과).
        - "tool_handlers": dict[str, Callable[[dict], Any|Coroutine]] — name → 핸들러.
        - "tool_strategy": "none" | "official" | "prompted" — 모델별 도구 prompt 방식.
        """
        # Claude 의 SYSTEM_PROMPT 는 도구 호출 가정 — Qwen 에게 주면 가짜 JSON
        # 생성 회귀. 우리 전용 prompt 사용.
        self._system_prompt = _QWEN_SYSTEM_PROMPT
        self._history = []
        self._openai_tools = list(tools.get("openai_tools") or [])
        self._tool_handlers = dict(tools.get("tool_handlers") or {})
        self._tool_strategy = str(tools.get("tool_strategy") or "none")

    def clear_history(self) -> None:
        """대화 누적 초기화 — runtime.clear_session() / set_model() 진입점에서 호출."""
        self._history = []

    def _effective_system_prompt(self) -> str:
        """tool_strategy 별 system prompt 구성.

        - "none" / "official": 기본 _QWEN_SYSTEM_PROMPT 그대로 ("official" 은 chat_template
          의 tools= 인자가 도구 안내를 자동 추가하므로 system prompt 손대지 않음).
        - "prompted": 기본 prompt + build_prompted_tool_catalog 추가 — 모델이 도구 알게.
        """
        if self._tool_strategy == "prompted" and self._openai_tools:
            from .tool_adapter import build_prompted_tool_catalog
            catalog = build_prompted_tool_catalog(self._openai_tools)
            return self._system_prompt + catalog
        return self._system_prompt

    def _build_conversation(self, msg: ChatInput) -> list[dict]:
        """ChatInput → Qwen2.5-Omni conversation list (HF 모델카드 형식).

        형식: [system, *history (user/assistant 누적), 새 user].
        text-only user: content = string.
        with images: content = list of image + text blocks. PNG bytes 는 임시 파일로
        저장 후 path 사용 (Qwen processor 가 path 만 받음).

        임시 파일은 self._temp_files 에 추적 — send_message finally 에서 정리.
        audio/video 는 sub-plan 7 — 현 단계는 무시.

        부수 효과: 새 user 메시지를 self._history 에 append. assistant 응답은
        send_message 가 generate 후 _commit_assistant_to_history() 로 append.
        """
        import tempfile

        # system + 누적된 history (이전 turn 의 user/assistant) 부터.
        conv: list[dict] = [
            {"role": "system",
             "content": [{"type": "text", "text": self._effective_system_prompt()}]},
        ]
        conv.extend(self._history)

        # 새 user 메시지 빌드.
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
            new_user = {"role": "user", "content": content_blocks}
        else:
            new_user = {"role": "user", "content": msg.text}

        conv.append(new_user)
        # history 에도 누적 — 다음 turn 에서 같이 보냄.
        self._history.append(new_user)
        return conv

    def _commit_assistant_to_history(self, text: str) -> None:
        """generate 끝난 응답을 history 에 append — 다음 turn 컨텍스트 유지."""
        if text:
            self._history.append({"role": "assistant", "content": text})

    def _cleanup_temp_files(self) -> None:
        """send_message finally — 추적된 temp 파일 모두 unlink."""
        for p in self._temp_files:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                _log.exception("TransformersBackend: temp 파일 정리 실패 %s", p)
        self._temp_files.clear()

    async def close(self) -> None:
        """모델 unload + gc — VRAM 회수. history 도 리셋."""
        self._model = None
        self._processor = None
        self._history = []
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
        """텍스트/이미지 + tool use 통합 처리.

        흐름:
        1. 모델 로드 + conversation 빌드.
        2. _run_one_generate — 한 번 generate (streaming + tool_call 파싱).
           반환: (full_text, tool_calls).
        3. tool_calls 있으면 각 handler 호출 + tool_result 메시지 conversation 에 append
           → 다시 _run_one_generate. 이 turn 의 tool_calls 가 빌 때까지 반복 (최대 _MAX_TOOL_ROUNDS).
        4. 최종 텍스트 → emit + history 에 append.
        """
        try:
            await self._ensure_model_loaded(emit_fn=emit_fn)
            emit_fn(AgentEvent(kind="started"))

            from .tool_adapter import build_tool_result_message
            from .tool_runtime import NormalizedToolCall, execute_tool_call

            conversation = self._build_conversation(msg)
            # _build_conversation 가 새 user 를 self._history 에 append 했음.
            # tool 루프 도중에도 self._history 와 conversation 양쪽에 결과 append.

            retry_used = False
            for _round in range(_MAX_TOOL_ROUNDS):
                full_text, tool_calls = await self._run_one_generate(conversation, emit_fn)

                # tool_call 태그는 보이는데 parse 가 0개 → schema 위반.
                # 모델이 호출 의도였지만 형식 망친 케이스 — 한 번 재시도, 두 번째도 망치면 skip.
                if "<tool_call>" in full_text and not tool_calls:
                    if not retry_used:
                        retry_used = True
                        emit_fn(AgentMessage(
                            role="system",
                            text="⚠ 도구 호출 형식 오류 — 한 번 재시도합니다.",
                        ))
                        # broken assistant turn 도 conversation/history 에 append —
                        # strict alternation 요구하는 chat_template 가 user-user 연속에서
                        # 에러 안 내도록. 다음 hint user 가 그 다음에 정상 추가됨.
                        conversation.append({"role": "assistant", "content": full_text})
                        self._history.append({"role": "assistant", "content": full_text})
                        # 재시도 hint 를 conversation 에 user 로 append.
                        hint_msg = {
                            "role": "user",
                            "content": "이전 응답의 <tool_call> JSON 형식이 잘못되었습니다. "
                                       "정확한 JSON 으로 다시 호출하거나 일반 텍스트로 답하세요.",
                        }
                        conversation.append(hint_msg)
                        self._history.append(hint_msg)
                        continue
                    else:
                        emit_fn(AgentMessage(
                            role="system",
                            text="⚠ 도구 호출 형식 재시도 후에도 오류 — 이번 도구 호출은 건너뜁니다.",
                        ))
                        self._commit_assistant_to_history(full_text)
                        emit_fn(AgentEvent(kind="done"))
                        return

                if not tool_calls:
                    # 최종 답변 — history 에 누적 + done emit.
                    self._commit_assistant_to_history(full_text)
                    emit_fn(AgentEvent(kind="done"))
                    return

                # tool_call 한 assistant turn 도 history 에 누적 (텍스트 + 태그 모두).
                # Qwen 이 다음 generate 에서 자기가 어떤 호출했는지 알도록.
                conversation.append({"role": "assistant", "content": full_text})
                self._history.append({"role": "assistant", "content": full_text})

                # 핸들러 실행 + emit + 결과 메시지 conversation/history 에 append.
                # execute_tool_call 이 tool_use + tool_result UI emit + body 직렬화까지 처리.
                for call in tool_calls:
                    norm = NormalizedToolCall(
                        id=call.get("id"), name=call["name"], arguments=call["arguments"],
                    )
                    body = await execute_tool_call(norm, self._tool_handlers, emit_fn)
                    result_msg = build_tool_result_message(call["id"], body)
                    conversation.append(result_msg)
                    self._history.append(result_msg)

            # 루프 한계 초과 — 안전망.
            emit_fn(AgentMessage(
                role="system",
                text=f"⚠ 도구 호출 루프 한계 ({_MAX_TOOL_ROUNDS} 라운드) 초과 — 중단.",
            ))
            emit_fn(AgentEvent(kind="done"))
        except Exception as exc:
            # detail 에 짧은 traceback 도 같이 — 사용자가 KStudio 콘솔/로그 못 봐도
            # 채팅 메시지에서 정확한 발생 위치 노출 (멀티모달 로드/파싱 디버깅).
            # str(exc) 가 빈 경우 (일부 transformers 예외) repr 폴백.
            import traceback as _tb
            tb_tail = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))[-1200:]
            detail = str(exc) or repr(exc) or type(exc).__name__
            _log.exception("TransformersBackend: send_message 실패")
            emit_fn(AgentEvent(
                kind="error",
                detail=f"{detail}\n--- traceback (마지막 1200자) ---\n{tb_tail}",
            ))
        finally:
            self._stop_flag = None
            self._cleanup_temp_files()

    async def _run_one_generate(
        self, conversation: list[dict], emit_fn: EmitFn,
    ) -> tuple[str, list[dict]]:
        """한 번 generate 실행 — streaming 으로 텍스트 emit + 끝나면 (full_text, tool_calls) 반환.

        tool_call 태그가 있으면 그건 emit 하지 않음 (UI 잡음 방지) — strip 후 빈 텍스트면
        assistant chunk 도 emit 안 함. 호출자가 tool_calls 받아 처리.

        Note: <tool_call> 감지는 누적 텍스트 단위로 하므로 청크 경계에서 태그가 분리된 경우
        (예: '<tool_' + 'call>...') 에는 앞 부분이 emit 될 수 있음. 실제 Qwen streaming 에서
        발생 가능하나 현재 테스트 범위 밖 — 향후 정밀 prefix 감지로 개선 가능.
        """
        from transformers import TextIteratorStreamer
        from .tool_adapter import parse_tool_calls

        tools_arg = self._openai_tools if self._tool_strategy == "official" else None
        text = self._processor.apply_chat_template(
            conversation, tools=tools_arg,
            add_generation_prompt=True, tokenize=False,
        )

        streamer = TextIteratorStreamer(
            self._processor, skip_prompt=True, skip_special_tokens=True,
        )
        self._stop_flag = threading.Event()
        stopping = self._make_stopping_criteria(self._stop_flag)

        if self._is_text_only():
            # text-only 경로 — tokenizer 만 사용. Omni 전용 인자 제거.
            inputs = self._processor(text, return_tensors="pt", padding=True)
            inputs = inputs.to(self._model.device)
            # Long tensor (input_ids) 는 dtype 변환 불필요 — .to(dtype) 생략.
            gen_kwargs = dict(
                **inputs, streamer=streamer,
                stopping_criteria=stopping,
                max_new_tokens=512, do_sample=False,
            )
        else:
            # Omni 경로 — process_mm_info + Omni 전용 kwargs.
            from qwen_omni_utils import process_mm_info
            audios, images, videos = process_mm_info(conversation, use_audio_in_video=False)
            inputs = self._processor(
                text=text, audio=audios, images=images, videos=videos,
                return_tensors="pt", padding=True, use_audio_in_video=False,
            )
            inputs = inputs.to(self._model.device).to(self._model.dtype)
            gen_kwargs = dict(
                **inputs, streamer=streamer,
                return_audio=False, use_audio_in_video=False,
                stopping_criteria=stopping,
                max_new_tokens=512, do_sample=False,
            )

        gen_error: dict[str, BaseException] = {}

        def _run_generate():
            try:
                self._model.generate(**gen_kwargs)
            except BaseException as e:  # noqa: BLE001 — propagate to main
                _log.exception("TransformersBackend: generate thread 실패")
                gen_error["exc"] = e
                streamer.end()

        thread = threading.Thread(target=_run_generate, daemon=True)
        thread.start()

        loop = asyncio.get_running_loop()
        iter_streamer = iter(streamer)
        chunks: list[str] = []
        # 누적 텍스트에서 <tool_call> 보이면 그 시점부터 emit 중단 — UI 잡음 방지.
        # 정밀 분리 (태그 일부가 chunk 경계에 걸린 경우) 는 단순화 위해 strip_tool_call_tags
        # 가 끝에서 한 번에 처리. emit 은 보수적으로: <tool_call> 첫 발견 시 멈춤.
        emitted_so_far = ""
        tool_call_seen = False
        while True:
            chunk = await loop.run_in_executor(None, _next_or_sentinel, iter_streamer)
            if chunk is _STREAM_SENTINEL:
                break
            if not chunk:
                continue
            chunks.append(chunk)
            if not tool_call_seen:
                if "<tool_call>" in (emitted_so_far + chunk):
                    tool_call_seen = True
                else:
                    emit_fn(AgentMessage(role="assistant", text=chunk))
                    emitted_so_far += chunk

        await asyncio.to_thread(thread.join)
        if "exc" in gen_error:
            raise gen_error["exc"]
        full_text = "".join(chunks)
        tool_calls = parse_tool_calls(full_text) if self._openai_tools else []
        return full_text, tool_calls

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

    def _build_quantization_config(self) -> "Any | None":
        """load_in_4bit=True 면 NF4 + double quant + bf16 compute 의 BitsAndBytesConfig.

        flash-attn 미지원 GPU (Blackwell/sm_120 — RTX 5060/5090) 에서 가장 효과 큰
        가속 옵션 (2026-05-22 smoke test 확인). 외부 의존: bitsandbytes ≥ 0.43 + torch.

        llm_int8_enable_fp32_cpu_offload=True — Qwen2.5-Omni 같이 thinker + talker 합쳐
        ~10B 인 모델은 4-bit 양자화 + 비양자화 encoder/talker 합쳐 16GB GPU 에 빠듯.
        accelerate 가 talker (speech 전용, 우리가 안 씀) 같은 모듈을 CPU 로 보낼 수
        있게 허용 — 핵심 thinker 는 GPU 유지되니 generate 속도 영향 거의 없음.
        """
        if not self._load_in_4bit:
            return None
        import torch
        from transformers import BitsAndBytesConfig
        return BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
            llm_int8_enable_fp32_cpu_offload=True,
        )

    async def _ensure_model_loaded(self, emit_fn: "EmitFn | None" = None) -> None:
        """첫 호출 시 transformers import + 모델 로드. 이후 호출은 캐싱.

        emit_fn: 옵션 — 로드 시작/완료 시 시스템 메시지 emit. None 이면 silent.
        사용자가 첫 메시지 후 30초+ 대기하는 동안 진행 상황 모르는 문제 해결.

        속도/메모리 최적화:
        - attn_implementation="sdpa" — PyTorch built-in scaled_dot_product_attention.
          기본 eager 보다 2-3배 빠름. flash-attn 별도 설치 없이 즉시 적용. Blackwell
          (sm_120, RTX 5060 Ti 등) 에서도 efficient attention 으로 폴백 동작 (flash-attn
          은 sm_120 커널 미지원 → 이 GPU 군에선 sdpa 가 최선).
        - load_in_4bit=True (옵션) — bitsandbytes NF4 4-bit. VRAM 절반 + 속도 1.3~1.7배.
        - Omni: 모델 로드 후 disable_talker() — Qwen2.5-Omni 의 speech 생성 모듈 (~2GB
          VRAM) 해제. text/image 만 쓰므로 불필요.

        분기:
        - text-only (_is_text_only()): AutoModelForCausalLM + AutoTokenizer.
        - 멀티모달 (기본): Qwen2_5OmniForConditionalGeneration + Qwen2_5OmniProcessor.
        """
        if self._model is not None and self._processor is not None:
            return
        import time
        _t0 = time.time()
        if emit_fn is not None:
            emit_fn(AgentMessage(
                role="system",
                text=f"🔄 {self._repo_id} 로딩 중... (수십 초 걸릴 수 있습니다)",
            ))
        quant_config = self._build_quantization_config()
        # 4-bit 양자화 시엔 torch_dtype 명시 X (BitsAndBytesConfig 의 compute_dtype 가 우선).
        common_kwargs: dict[str, Any] = {
            "device_map": "auto",
            "attn_implementation": "sdpa",
        }
        if quant_config is not None:
            common_kwargs["quantization_config"] = quant_config
        else:
            common_kwargs["torch_dtype"] = "auto"

        if self._is_text_only():
            from transformers import AutoModelForCausalLM, AutoTokenizer
            self._model = await asyncio.to_thread(
                AutoModelForCausalLM.from_pretrained,
                self._repo_id,
                **common_kwargs,
            )
            self._processor = await asyncio.to_thread(
                AutoTokenizer.from_pretrained,
                self._repo_id,
            )
            if emit_fn is not None:
                emit_fn(AgentMessage(
                    role="system",
                    text=f"✅ 모델 준비 완료 ({time.time()-_t0:.1f}초)",
                ))
            return
        # Omni 경로 — 멀티모달 (image/audio/video 포함).
        from transformers import (
            Qwen2_5OmniForConditionalGeneration,
            Qwen2_5OmniProcessor,
        )
        self._model = await asyncio.to_thread(
            Qwen2_5OmniForConditionalGeneration.from_pretrained,
            self._repo_id,
            **common_kwargs,
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
        if emit_fn is not None:
            emit_fn(AgentMessage(
                role="system",
                text=f"✅ 모델 준비 완료 ({time.time()-_t0:.1f}초)",
            ))
