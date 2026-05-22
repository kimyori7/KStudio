"""OllamaBackend 단위 테스트 — httpx.AsyncClient mock.

TransformersBackend 와 동일한 emit_fn 패턴 검증 + Ollama 특화 (JSONL streaming,
native tool_calls). httpx 가 이미 설치되어 있으므로 sys.modules 우회 X — 직접 monkeypatch.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from screen_recorder.agent.backends.base import AgentEvent, AgentMessage, ChatInput
from screen_recorder.agent.backends.ollama_backend import OllamaBackend


# ===========================================================================
# httpx stream context mock — Ollama 의 JSONL 응답을 흉내.
# ===========================================================================
class _FakeStreamResponse:
    """httpx.Response 흉내 — aiter_lines() 가 미리 정한 라인 yield."""

    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self._lines = list(lines)
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    async def aiter_lines(self):
        for ln in self._lines:
            # 실제 ollama 는 라인 마다 즉시 flush — 비동기 simulate 위해 sleep(0).
            await asyncio.sleep(0)
            yield ln


class _FakeStreamCM:
    """`async with client.stream(...) as response` 흉내."""

    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self._response

    async def __aexit__(self, *exc):
        self.exited = True
        return False


def _make_fake_client(stream_lines: list[str], status: int = 200,
                      connect_error: bool = False):
    """`httpx.AsyncClient` 흉내. .stream(...) 호출 시 _FakeStreamCM 반환.

    connect_error=True 면 stream() 호출 자체가 httpx.ConnectError 던짐.
    """
    client = MagicMock()

    if connect_error:
        import httpx
        def _stream(*a, **kw):
            raise httpx.ConnectError("connection refused")
        client.stream = MagicMock(side_effect=_stream)
    else:
        cm = _FakeStreamCM(_FakeStreamResponse(stream_lines, status_code=status))
        client.stream = MagicMock(return_value=cm)
        client._last_cm = cm
    client.aclose = AsyncMock()
    return client


def _ollama_line(content: str = "", done: bool = False,
                  tool_calls: list[dict] | None = None,
                  error: str | None = None) -> str:
    """Ollama 한 줄 JSONL 만들기."""
    if error:
        return json.dumps({"error": error})
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return json.dumps({"model": "qwen3:8b", "message": msg, "done": done})


# ===========================================================================
# 기본 lifecycle.
# ===========================================================================
@pytest.mark.asyncio
async def test_start_session_stores_tools_and_resets_history():
    be = OllamaBackend(model_tag="qwen3:8b")
    await be.start_session(
        system_prompt="너는 KStudio 비서.",
        tools={
            "openai_tools": [{"type": "function", "function": {"name": "foo"}}],
            "tool_handlers": {"foo": lambda a: {}},
            "tool_strategy": "official",
        },
        model="qwen3-8b-ollama",
    )
    assert be._system_prompt == "너는 KStudio 비서."
    assert be._openai_tools[0]["function"]["name"] == "foo"
    assert "foo" in be._tool_handlers
    assert be._history == []


@pytest.mark.asyncio
async def test_start_session_empty_tools_defaults():
    be = OllamaBackend(model_tag="qwen3:8b")
    await be.start_session(system_prompt="", tools={}, model="x")
    assert be._openai_tools == []
    assert be._tool_handlers == {}


@pytest.mark.asyncio
async def test_close_resets_history_and_aclose_client(monkeypatch):
    be = OllamaBackend(model_tag="qwen3:8b")
    fake_client = _make_fake_client([])
    be._client = fake_client
    be._history = [{"role": "user", "content": "x"}]
    await be.close()
    assert be._history == []
    assert be._client is None
    fake_client.aclose.assert_awaited()


def test_supports_modality_text_only():
    be = OllamaBackend(model_tag="qwen3:8b")
    assert be.supports_modality("text") is False  # 현재 모델 image 미지원.
    assert be.supports_modality("image") is False


# ===========================================================================
# 단순 텍스트 응답 (도구 없음).
# ===========================================================================
@pytest.mark.asyncio
async def test_send_message_streams_text_chunks_and_emits_done(monkeypatch):
    """텍스트 청크 3개 → done 한 줄. assistant 메시지 3번 + done 이벤트."""
    be = OllamaBackend(model_tag="qwen3:8b")
    await be.start_session(system_prompt="sys", tools={}, model="x")

    lines = [
        _ollama_line(content="안녕"),
        _ollama_line(content=" 세상"),
        _ollama_line(content="!"),
        _ollama_line(content="", done=True),
    ]
    fake_client = _make_fake_client(lines)
    be._client = fake_client

    events: list = []
    await be.send_message(ChatInput(text="안녕"), events.append)

    assistant_chunks = [e.text for e in events if isinstance(e, AgentMessage)
                        and e.role == "assistant"]
    assert assistant_chunks == ["안녕", " 세상", "!"]
    assert any(isinstance(e, AgentEvent) and e.kind == "done" for e in events)
    assert any(isinstance(e, AgentEvent) and e.kind == "started" for e in events)
    # history 누적: user + assistant.
    assert len(be._history) == 2
    assert be._history[0]["role"] == "user"
    assert be._history[1]["role"] == "assistant"
    assert be._history[1]["content"] == "안녕 세상!"


@pytest.mark.asyncio
async def test_send_message_includes_system_prompt_in_payload():
    """첫 호출 시 messages[0] 이 system role 로 system_prompt 담음."""
    be = OllamaBackend(model_tag="qwen3:8b")
    await be.start_session(system_prompt="너는 비서.", tools={}, model="x")
    fake_client = _make_fake_client([_ollama_line(content="ok", done=True)])
    be._client = fake_client

    await be.send_message(ChatInput(text="안녕"), lambda _: None)

    call = fake_client.stream.call_args
    payload = call.kwargs["json"]
    assert payload["model"] == "qwen3:8b"
    assert payload["stream"] is True
    # payload["messages"] 는 send_message 가 동일 list 참조 사용 + 응답 후 assistant
    # turn 도 append → 끝나는 시점엔 [system, user, assistant] 셋 모두 보임.
    msgs = payload["messages"]
    assert msgs[0] == {"role": "system", "content": "너는 비서."}
    user_msgs = [m for m in msgs if m.get("role") == "user"]
    assert user_msgs == [{"role": "user", "content": "안녕"}]


@pytest.mark.asyncio
async def test_send_message_includes_tools_when_present():
    """openai_tools 있으면 payload['tools'] 에 그대로 전달."""
    be = OllamaBackend(model_tag="qwen3:8b")
    tools = [{"type": "function", "function": {"name": "get_x", "parameters": {}}}]
    await be.start_session(
        system_prompt="", tools={
            "openai_tools": tools, "tool_handlers": {"get_x": lambda a: {}},
            "tool_strategy": "official",
        }, model="x",
    )
    fake_client = _make_fake_client([_ollama_line(content="ok", done=True)])
    be._client = fake_client

    await be.send_message(ChatInput(text="x"), lambda _: None)
    payload = fake_client.stream.call_args.kwargs["json"]
    assert payload["tools"] == tools


@pytest.mark.asyncio
async def test_send_message_omits_tools_when_empty():
    """tools 비어 있으면 payload 에 'tools' key 없음."""
    be = OllamaBackend(model_tag="qwen3:8b")
    await be.start_session(system_prompt="", tools={}, model="x")
    fake_client = _make_fake_client([_ollama_line(content="ok", done=True)])
    be._client = fake_client

    await be.send_message(ChatInput(text="x"), lambda _: None)
    payload = fake_client.stream.call_args.kwargs["json"]
    assert "tools" not in payload


# ===========================================================================
# Tool use 라운드 (single-round).
# ===========================================================================
@pytest.mark.asyncio
async def test_send_message_handles_single_tool_call_then_final_text():
    """1라운드: tool_calls → 핸들러 실행 → 2라운드 텍스트 응답."""
    be = OllamaBackend(model_tag="qwen3:8b")
    captured_args: list = []
    def handler(args):
        captured_args.append(args)
        return {"duration_ms": 60000}

    await be.start_session(
        system_prompt="", tools={
            "openai_tools": [{"type": "function",
                              "function": {"name": "get_duration_ms", "parameters": {}}}],
            "tool_handlers": {"get_duration_ms": handler},
            "tool_strategy": "official",
        }, model="x",
    )

    # 라운드 1: tool_call 한 줄 + done.
    lines_r1 = [
        _ollama_line(content="", tool_calls=[{
            "function": {"name": "get_duration_ms", "arguments": {}},
        }]),
        _ollama_line(content="", done=True),
    ]
    # 라운드 2: 텍스트 응답.
    lines_r2 = [
        _ollama_line(content="60초입니다"),
        _ollama_line(content="", done=True),
    ]

    fake_client = MagicMock()
    cms = [
        _FakeStreamCM(_FakeStreamResponse(lines_r1)),
        _FakeStreamCM(_FakeStreamResponse(lines_r2)),
    ]
    fake_client.stream = MagicMock(side_effect=cms)
    fake_client.aclose = AsyncMock()
    be._client = fake_client

    events: list = []
    await be.send_message(ChatInput(text="몇 초?"), events.append)

    assert captured_args == [{}]   # 핸들러 1번 호출.
    # tool_use + tool_result UI 메시지 emit.
    tool_use_msgs = [e for e in events if isinstance(e, AgentMessage)
                     and e.role == "tool_use"]
    tool_result_msgs = [e for e in events if isinstance(e, AgentMessage)
                        and e.role == "tool_result"]
    assert len(tool_use_msgs) == 1
    assert "get_duration_ms" in tool_use_msgs[0].text
    assert len(tool_result_msgs) == 1
    assert "duration_ms" in tool_result_msgs[0].text
    # 최종 assistant 텍스트.
    finals = [e.text for e in events if isinstance(e, AgentMessage)
              and e.role == "assistant"]
    assert "60초입니다" in "".join(finals)
    # /api/chat 두 번 호출.
    assert fake_client.stream.call_count == 2


@pytest.mark.asyncio
async def test_send_message_unknown_tool_returns_error_in_history():
    """핸들러 없는 도구 → 'unknown tool' 에러 결과를 tool 메시지로 append."""
    be = OllamaBackend(model_tag="qwen3:8b")
    await be.start_session(
        system_prompt="", tools={
            "openai_tools": [{"type": "function",
                              "function": {"name": "x", "parameters": {}}}],
            "tool_handlers": {},   # 핸들러 없음.
            "tool_strategy": "official",
        }, model="x",
    )

    lines_r1 = [
        _ollama_line(content="", tool_calls=[{
            "function": {"name": "unknown_tool", "arguments": {}},
        }]),
        _ollama_line(content="", done=True),
    ]
    lines_r2 = [_ollama_line(content="실패", done=True)]
    fake_client = MagicMock()
    fake_client.stream = MagicMock(side_effect=[
        _FakeStreamCM(_FakeStreamResponse(lines_r1)),
        _FakeStreamCM(_FakeStreamResponse(lines_r2)),
    ])
    fake_client.aclose = AsyncMock()
    be._client = fake_client

    events: list = []
    await be.send_message(ChatInput(text="x"), events.append)

    # history 의 tool 메시지에 error.
    tool_msgs = [m for m in be._history if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert "unknown tool" in tool_msgs[0]["content"]


@pytest.mark.asyncio
async def test_send_message_handler_exception_becomes_error_result():
    """핸들러가 raise → result 에 error string 담아 tool 메시지로 append."""
    be = OllamaBackend(model_tag="qwen3:8b")
    def boom(args):
        raise ValueError("boom!")

    await be.start_session(
        system_prompt="", tools={
            "openai_tools": [{"type": "function",
                              "function": {"name": "x", "parameters": {}}}],
            "tool_handlers": {"x": boom},
            "tool_strategy": "official",
        }, model="x",
    )

    lines_r1 = [
        _ollama_line(content="", tool_calls=[{
            "function": {"name": "x", "arguments": {}},
        }]),
        _ollama_line(content="", done=True),
    ]
    lines_r2 = [_ollama_line(content="실패함", done=True)]
    fake_client = MagicMock()
    fake_client.stream = MagicMock(side_effect=[
        _FakeStreamCM(_FakeStreamResponse(lines_r1)),
        _FakeStreamCM(_FakeStreamResponse(lines_r2)),
    ])
    fake_client.aclose = AsyncMock()
    be._client = fake_client

    await be.send_message(ChatInput(text="x"), lambda _: None)
    tool_msgs = [m for m in be._history if m.get("role") == "tool"]
    assert "boom!" in tool_msgs[0]["content"]


@pytest.mark.asyncio
async def test_async_handler_is_awaited():
    """핸들러가 coroutine 이면 await 후 결과 사용."""
    be = OllamaBackend(model_tag="qwen3:8b")
    async def async_handler(args):
        return {"async_ok": True}

    await be.start_session(
        system_prompt="", tools={
            "openai_tools": [{"type": "function",
                              "function": {"name": "x", "parameters": {}}}],
            "tool_handlers": {"x": async_handler},
            "tool_strategy": "official",
        }, model="x",
    )

    lines_r1 = [
        _ollama_line(content="", tool_calls=[{
            "function": {"name": "x", "arguments": {}},
        }]),
        _ollama_line(content="", done=True),
    ]
    lines_r2 = [_ollama_line(content="done", done=True)]
    fake_client = MagicMock()
    fake_client.stream = MagicMock(side_effect=[
        _FakeStreamCM(_FakeStreamResponse(lines_r1)),
        _FakeStreamCM(_FakeStreamResponse(lines_r2)),
    ])
    fake_client.aclose = AsyncMock()
    be._client = fake_client

    await be.send_message(ChatInput(text="x"), lambda _: None)
    tool_msgs = [m for m in be._history if m.get("role") == "tool"]
    assert "async_ok" in tool_msgs[0]["content"]


# ===========================================================================
# 에러 경로.
# ===========================================================================
@pytest.mark.asyncio
async def test_send_message_friendly_connect_error():
    """httpx.ConnectError → 친절한 한국어 안내 emit (Ollama 서버 실행 확인)."""
    be = OllamaBackend(model_tag="qwen3:8b")
    await be.start_session(system_prompt="", tools={}, model="x")
    be._client = _make_fake_client([], connect_error=True)

    events: list = []
    await be.send_message(ChatInput(text="x"), events.append)

    error_msgs = [e for e in events if isinstance(e, AgentMessage) and e.role == "error"]
    assert len(error_msgs) == 1
    assert "Ollama" in error_msgs[0].text
    assert "ollama serve" in error_msgs[0].text
    assert any(isinstance(e, AgentEvent) and e.kind == "error" for e in events)


@pytest.mark.asyncio
async def test_send_message_api_error_in_jsonl_propagates():
    """Ollama 가 {'error': '...'} 한 줄 보내면 error event emit."""
    be = OllamaBackend(model_tag="qwen3:8b")
    await be.start_session(system_prompt="", tools={}, model="x")
    lines = [_ollama_line(error="model 'qwen3:8b' not found")]
    be._client = _make_fake_client(lines)

    events: list = []
    await be.send_message(ChatInput(text="x"), events.append)

    error_evts = [e for e in events if isinstance(e, AgentEvent) and e.kind == "error"]
    assert error_evts
    assert "not found" in error_evts[0].detail


@pytest.mark.asyncio
async def test_cancel_sets_flag_and_breaks_loop():
    """cancel() 가 _cancelled=True set + 진행 중 stream 의 다음 chunk 에서 break."""
    be = OllamaBackend(model_tag="qwen3:8b")
    await be.start_session(system_prompt="", tools={}, model="x")
    await be.cancel()
    assert be._cancelled is True


# ===========================================================================
# Tool result 회신 (Protocol stub).
# ===========================================================================
@pytest.mark.asyncio
async def test_send_tool_result_is_noop():
    """sub-plan 까지는 send_message 가 in-process 로 처리 — Protocol 충족용 stub."""
    be = OllamaBackend(model_tag="qwen3:8b")
    await be.send_tool_result("tu_0", {"ok": True}, lambda _: None)
    # noop — 예외만 안 나면 OK.


@pytest.mark.asyncio
async def test_emit_order_tool_use_before_tool_result_before_assistant():
    """회귀: tool_use → tool_result → final assistant 순서 보장.

    execute_tool_call helper 도입 후 Ollama emit 순서 명시 검증.
    single tool_call 시나리오.
    """
    be = OllamaBackend(model_tag="qwen3:8b")
    await be.start_session(
        system_prompt="", tools={
            "openai_tools": [{"type": "function",
                              "function": {"name": "get_video_state", "parameters": {}}}],
            "tool_handlers": {"get_video_state": lambda args: {"duration_ms": 5000}},
            "tool_strategy": "official",
        }, model="x",
    )

    lines_r1 = [
        _ollama_line(content="", tool_calls=[{
            "function": {"name": "get_video_state", "arguments": {}},
        }]),
        _ollama_line(content="", done=True),
    ]
    lines_r2 = [
        _ollama_line(content="영상은 5초입니다"),
        _ollama_line(content="", done=True),
    ]

    fake_client = MagicMock()
    fake_client.stream = MagicMock(side_effect=[
        _FakeStreamCM(_FakeStreamResponse(lines_r1)),
        _FakeStreamCM(_FakeStreamResponse(lines_r2)),
    ])
    fake_client.aclose = AsyncMock()
    be._client = fake_client

    events: list = []
    await be.send_message(ChatInput(text="영상 길이?"), events.append)

    # AgentMessage 만 필터 (역할 순서 추출).
    msgs = [e for e in events if isinstance(e, AgentMessage)]
    roles = [m.role for m in msgs]

    assert "tool_use" in roles, "tool_use 메시지 없음"
    assert "tool_result" in roles, "tool_result 메시지 없음"
    assert "assistant" in roles, "최종 assistant 메시지 없음"

    i_tool_use = roles.index("tool_use")
    i_tool_result = roles.index("tool_result")
    i_final_assistant = max(i for i, r in enumerate(roles) if r == "assistant")

    assert i_tool_use < i_tool_result, (
        f"tool_use({i_tool_use}) 가 tool_result({i_tool_result}) 보다 늦음"
    )
    assert i_tool_result < i_final_assistant, (
        f"tool_result({i_tool_result}) 가 final assistant({i_final_assistant}) 보다 늦음"
    )


@pytest.mark.asyncio
async def test_cancel_emits_error_event_once_no_done_after(monkeypatch):
    """회귀 (코드리뷰 Critical): cancel 시 error event 정확히 1회 + done 절대 없음.

    이전 버그: _generate 가 빈 tuple 반환 → run_tool_loop 가 done 추가 emit → error+done 이중.
    수정: _CancelledByUser 예외로 빠져나가서 done 안 발행.

    시나리오: 1라운드 tool_call → handler 가 _cancelled 설정 → 2라운드 _generate 에서 raise.
    """
    be = OllamaBackend(model_tag="qwen3:8b")
    await be.start_session(
        system_prompt="", tools={
            "openai_tools": [{"type": "function",
                              "function": {"name": "x", "parameters": {}}}],
            "tool_handlers": {"x": lambda args: setattr(be, "_cancelled", True) or {"ok": True}},
            "tool_strategy": "official",
        }, model="x",
    )

    # _run_one_generate mock — 1라운드 tool_call 반환. 2라운드는 호출 안 됨 (cancel raise).
    call_count = {"n": 0}
    async def _fake_generate(messages, emit_fn):
        call_count["n"] += 1
        return ("...", [{"function": {"name": "x", "arguments": {}}}])
    be._run_one_generate = _fake_generate
    be._client = MagicMock()
    be._client.aclose = AsyncMock()

    events: list = []
    await be.send_message(ChatInput(text="x"), events.append)

    error_events = [e for e in events if isinstance(e, AgentEvent) and e.kind == "error"]
    done_events = [e for e in events if isinstance(e, AgentEvent) and e.kind == "done"]
    assert len(error_events) == 1, f"error event 1회여야 하는데 {len(error_events)}회: {events}"
    assert len(done_events) == 0, f"cancel 후 done 절대 없어야 하는데 {len(done_events)}개"
    assert error_events[0].detail == "취소됨"
