"""OllamaBackend — Ollama HTTP API (localhost:11434) 어댑터.

ChatBackend Protocol 구현. Ollama 가 GGUF 양자화 + llama.cpp 백엔드로 실행 →
transformers (bf16) 보다 5~10배 빠름. Qwen3 시리즈 등 tool calling 정식 지원
(chat_template + Ollama 가 `tool_calls` 필드로 파싱 후 반환 → 우리는 그대로 사용).

스레드 모델: 호출자 (runtime.py worker thread) 의 asyncio loop 위에서 await.
httpx.AsyncClient 로 비동기 HTTP — generate.py 같은 blocking 없음.

수명주기:
- start_session(): system_prompt + tools 저장. HTTP 클라이언트 lazy.
- send_message(): /api/chat 스트리밍 호출 → 텍스트/tool_calls emit → tool_call 있으면
  핸들러 실행 후 다시 호출 (multi-round 루프, 최대 _MAX_TOOL_ROUNDS).
- cancel(): 진행 중 요청 task 취소 → httpx 가 연결 종료 → Ollama 가 generate 중단.
- close(): httpx client 닫기 + history 리셋.

전제: 사용자가 Ollama 를 PC 에 설치 + `ollama serve` 가 백그라운드에서 동작 + 사용할
모델을 `ollama pull <tag>` 으로 받음. 검증/안내는 send_message 시점에 친절한
에러 메시지로 (factory 진입점에서는 단순 dep 체크만).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from .base import AgentEvent, AgentMessage, ChatInput, EmitFn


_log = logging.getLogger(__name__)


# tool use 무한루프 안전망. TransformersBackend 와 동일 상수.
_MAX_TOOL_ROUNDS = 5

# Ollama 기본 엔드포인트.
_DEFAULT_BASE_URL = "http://localhost:11434"

# Ollama 가 응답을 못 줄 때 (서버 down 등) UI 에 친절히 알릴 prefix.
_CONN_ERROR_HINT = (
    "Ollama 서버에 연결할 수 없습니다. 다음을 확인해 주세요:\n"
    "1. Ollama 가 PC 에 설치되어 있는지 (https://ollama.com/).\n"
    "2. `ollama serve` 가 백그라운드에서 실행 중인지 (Windows 는 보통 자동 시작).\n"
    "3. 사용할 모델이 다운로드 되어 있는지 (`ollama pull <model>`)."
)


# Qwen3 / Ollama 백엔드 전용 system prompt — Qwen 의 영상 도구 미지원 가정과 달리
# Qwen3 는 tool calling 정식 지원 (Ollama 가 native 처리) → Claude SYSTEM_PROMPT
# 그대로 받음. 호출자(runtime) 가 system_prompt 전달.


class OllamaBackend:
    """Ollama HTTP API 백엔드. /api/chat 스트리밍 + 네이티브 tool calling."""

    def __init__(
        self,
        model_tag: str,
        base_url: str = _DEFAULT_BASE_URL,
        think: bool = False,
    ) -> None:
        """model_tag: Ollama 태그 ('qwen3:8b', 'llama3:8b' 등) — HF repo_id 아님.

        think=False (기본) — Qwen3 의 reasoning mode 끔. 속도 우선.
        True 로 켜면 `<think>` 블록이 응답에 포함되어 UI 에 thinking role 로 표시 가능
        (현재 단계는 단순화 위해 그냥 텍스트로 emit).
        """
        self._model_tag = model_tag
        self._base_url = base_url.rstrip("/")
        self._think = think
        self._system_prompt: str = ""
        self._openai_tools: list[dict] = []
        self._tool_handlers: dict[str, Any] = {}
        # 누적 대화 — Claude SDK 와 달리 Ollama 도 직접 누적 필요. system 은 별도.
        # 형식: [{"role": "user"|"assistant"|"tool", "content": str, "tool_calls"?: list, "name"?: str}, ...]
        self._history: list[dict] = []
        self._client: Optional[Any] = None   # httpx.AsyncClient (lazy import)
        self._cancelled: bool = False
        self._current_request_cm: Any = None   # 진행 중 stream context — cancel 시 닫기.

    async def start_session(
        self, system_prompt: str, tools: dict[str, Any], model: str,
    ) -> None:
        """세션 초기화 — history 리셋 + system/tools 저장.

        tools dict shape — TransformersBackend 와 동일:
        - "openai_tools": list[dict] (mcp_to_openai_tools 결과).
        - "tool_handlers": dict[str, Callable].
        - "tool_strategy": "official" (Ollama Qwen3 는 정식) — 보관만, 분기 안 함.
        """
        self._system_prompt = system_prompt
        self._openai_tools = list(tools.get("openai_tools") or [])
        self._tool_handlers = dict(tools.get("tool_handlers") or {})
        self._history = []

    def clear_history(self) -> None:
        """대화 누적 초기화 — runtime.clear_session() 진입점에서 호출."""
        self._history = []

    async def close(self) -> None:
        """HTTP 클라이언트 닫기 + history 리셋. cancel 도 같이 시도."""
        self._cancelled = True
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                _log.exception("OllamaBackend: httpx aclose 실패")
            self._client = None
        self._history = []

    async def cancel(self) -> None:
        """진행 중 generate 취소 — 다음 chunk 읽기에서 break.

        httpx stream context 가 살아 있으면 닫아 Ollama 와의 connection 종료 → Ollama 가
        generate 중단. self._cancelled 플래그도 set → 루프가 즉시 break.
        """
        self._cancelled = True

    def supports_modality(self, modality: str) -> bool:
        # 현재 사용 모델 (Qwen3 8B) 은 text-only. 멀티모달 모델 추가 시 metadata 로 판단.
        return False

    def _ensure_client(self) -> None:
        """httpx.AsyncClient lazy 생성. timeout 크게 — 모델이 생각 오래 할 수 있음."""
        if self._client is not None:
            return
        import httpx
        # 첫 request 부터 generate 끝까지 한 stream 으로 받음 — read/connect/write 모두
        # 넉넉히. Ollama 가 모델 cold start (디스크 → RAM) 시 30초 이상 걸릴 수 있음.
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
        self._client = httpx.AsyncClient(timeout=timeout)

    def _build_messages(self, msg: ChatInput) -> list[dict]:
        """ChatInput + history → Ollama /api/chat 의 messages 배열.

        부수 효과: 새 user 메시지를 self._history 에 append.
        """
        messages: list[dict] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        messages.extend(self._history)
        # 이미지 등 멀티모달은 현재 모델 미지원 — 텍스트만.
        new_user = {"role": "user", "content": msg.text}
        messages.append(new_user)
        self._history.append(new_user)
        return messages

    async def send_message(self, msg: ChatInput, emit_fn: EmitFn) -> None:
        """텍스트 + tool use multi-round 처리.

        1. messages 빌드 → POST /api/chat stream=true.
        2. JSONL 한 줄씩 파싱 → message.content 청크 emit + tool_calls 누적.
        3. done=true 받으면 tool_calls 있는지 확인 — 있으면 핸들러 실행 후 tool 메시지
           append → 다시 호출. 없으면 done emit.
        4. _MAX_TOOL_ROUNDS 초과 시 안전망.
        """
        self._cancelled = False
        try:
            self._ensure_client()
            emit_fn(AgentEvent(kind="started"))

            messages = self._build_messages(msg)

            for _round in range(_MAX_TOOL_ROUNDS):
                if self._cancelled:
                    emit_fn(AgentEvent(kind="error", detail="취소됨"))
                    return

                full_text, tool_calls = await self._run_one_generate(messages, emit_fn)

                # 어시스턴트 turn 누적 — tool_calls 포함 (다음 라운드 모델이 자기 호출 기억).
                assistant_msg: dict[str, Any] = {"role": "assistant", "content": full_text}
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                messages.append(assistant_msg)
                self._history.append(assistant_msg)

                if not tool_calls:
                    emit_fn(AgentEvent(kind="done"))
                    return

                # tool_use UI emit + 핸들러 실행.
                for call in tool_calls:
                    fn = call.get("function") or {}
                    name = fn.get("name", "?")
                    args = fn.get("arguments") or {}
                    emit_fn(AgentEvent(
                        kind="tool_use", detail=f"{name} {args}",
                    ))
                    emit_fn(AgentMessage(
                        role="tool_use",
                        text=f"🔧 {name}({args})",
                        tool_name=name,
                    ))

                    handler = self._tool_handlers.get(name)
                    if handler is None:
                        result_val: Any = {"error": f"unknown tool: {name}"}
                    else:
                        try:
                            ret = handler(args)
                            if asyncio.iscoroutine(ret):
                                ret = await ret
                            result_val = ret
                        except Exception as exc:
                            _log.exception("ollama tool handler 실패: %s", name)
                            result_val = {"error": str(exc)}

                    # tool_result UI emit + conversation 에 tool 메시지 append.
                    body = (
                        result_val if isinstance(result_val, str)
                        else json.dumps(result_val, ensure_ascii=False, default=str)
                    )
                    preview = body[:200]
                    emit_fn(AgentMessage(
                        role="tool_result",
                        text=f"← {preview}",
                        tool_name=name,
                    ))
                    tool_msg = {"role": "tool", "content": body, "name": name}
                    messages.append(tool_msg)
                    self._history.append(tool_msg)

            # 루프 한계 초과.
            emit_fn(AgentMessage(
                role="system",
                text=f"⚠ 도구 호출 루프 한계 ({_MAX_TOOL_ROUNDS} 라운드) 초과 — 중단.",
            ))
            emit_fn(AgentEvent(kind="done"))
        except Exception as exc:
            # ConnectionError / ConnectError 는 친절한 안내 + 원인 같이.
            text = self._friendly_error_text(exc)
            _log.exception("OllamaBackend: send_message 실패")
            emit_fn(AgentMessage(role="error", text=text))
            emit_fn(AgentEvent(kind="error", detail=str(exc)))
        finally:
            self._current_request_cm = None

    def _friendly_error_text(self, exc: Exception) -> str:
        """ConnectError / TimeoutError 같이 자주 나는 케이스는 사용자에게 명확한 안내."""
        try:
            import httpx
            connect_errors = (httpx.ConnectError, httpx.ConnectTimeout)
        except Exception:
            connect_errors = ()   # httpx 미설치 (의존성 가드 누락) — 단순 str 폴백.

        # ConnectionRefusedError 도 같은 가족 (Windows 에서 자주).
        if isinstance(exc, connect_errors) or isinstance(exc, ConnectionRefusedError):
            return _CONN_ERROR_HINT + f"\n\n원인: {exc}"
        return f"⚠ Ollama 호출 실패: {exc}"

    async def _run_one_generate(
        self, messages: list[dict], emit_fn: EmitFn,
    ) -> tuple[str, list[dict]]:
        """한 번 /api/chat stream — 텍스트 chunk 마다 emit + (full_text, tool_calls) 반환.

        Ollama JSONL 응답:
            {"message":{"role":"assistant","content":"hi"},"done":false}
            {"message":{"role":"assistant","content":" there"},"done":false}
            {"message":{"role":"assistant","content":"","tool_calls":[...]},"done":false}
            {"message":{"role":"assistant","content":""},"done":true,"total_duration":...}

        tool_calls 는 한 chunk 에 한꺼번에 오거나, 메시지 끝에 done=true 와 같이 옴.
        우리는 모든 청크에서 tool_calls 누적해 마지막에 반환.
        """
        assert self._client is not None

        payload: dict[str, Any] = {
            "model": self._model_tag,
            "messages": messages,
            "stream": True,
            "think": self._think,
        }
        if self._openai_tools:
            payload["tools"] = self._openai_tools

        url = f"{self._base_url}/api/chat"
        chunks: list[str] = []
        tool_calls: list[dict] = []

        # stream context — cancel 가능하도록 self._current_request_cm 저장.
        cm = self._client.stream("POST", url, json=payload)
        self._current_request_cm = cm
        try:
            response = await cm.__aenter__()
            try:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if self._cancelled:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        _log.warning("ollama: JSON 파싱 실패 (skip): %s", line[:200])
                        continue
                    if "error" in evt:
                        raise RuntimeError(f"Ollama API 에러: {evt['error']}")
                    message = evt.get("message") or {}
                    content_chunk = message.get("content") or ""
                    if content_chunk:
                        chunks.append(content_chunk)
                        emit_fn(AgentMessage(role="assistant", text=content_chunk))
                    # tool_calls — 한 chunk 에 list 로 들어옴.
                    chunk_tool_calls = message.get("tool_calls") or []
                    for tc in chunk_tool_calls:
                        tool_calls.append(tc)
                    if evt.get("done"):
                        break
            finally:
                await cm.__aexit__(None, None, None)
        finally:
            self._current_request_cm = None

        return ("".join(chunks), tool_calls)

    async def send_tool_result(
        self, tool_use_id: str, result: Any, emit_fn: EmitFn,
    ) -> None:
        """send_message 가 in-process 로 tool 호출 처리 — 외부 호출자가 회신할 일 없음.

        ChatBackend Protocol 충족용 stub (TransformersBackend 와 동일).
        """
        _log.debug("OllamaBackend.send_tool_result: no-op (tool_use_id=%s)", tool_use_id)
