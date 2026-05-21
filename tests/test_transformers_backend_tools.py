"""TransformersBackend tool use 통합 — Hermes / Prompted 모드."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import MagicMock


# 기존 test_transformers_backend.py 의 transformers_mock fixture 와 동일 구조 —
# 한 곳에서 관리하려면 conftest.py 로 이동 가능 (이번 plan 범위 밖).
@pytest.fixture
def transformers_mock(monkeypatch):
    """transformers + qwen_omni_utils + torch 가짜 모듈 inject."""
    import sys
    fake_tf = MagicMock()
    fake_qou = MagicMock()
    fake_torch = MagicMock()
    monkeypatch.setitem(sys.modules, "transformers", fake_tf)
    monkeypatch.setitem(sys.modules, "qwen_omni_utils", fake_qou)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    return {"transformers": fake_tf, "qwen_omni_utils": fake_qou, "torch": fake_torch}


def test_start_session_stores_tool_strategy_and_tools():
    """start_session 가 tools dict 에서 openai_tools / tool_handlers / tool_strategy 받음."""
    from screen_recorder.agent.backends.transformers_backend import TransformersBackend

    backend = TransformersBackend(repo_id="Qwen/test")
    tools_dict = {
        "openai_tools": [{"type": "function", "function": {"name": "foo"}}],
        "tool_handlers": {"foo": lambda args: {"ok": True}},
        "tool_strategy": "official",
    }
    asyncio.run(backend.start_session(system_prompt="ignored", tools=tools_dict, model="x"))

    assert backend._openai_tools == tools_dict["openai_tools"]
    assert "foo" in backend._tool_handlers
    assert backend._tool_strategy == "official"


def test_start_session_defaults_when_tools_dict_empty():
    """tools 비어 있으면 tool_strategy='none' + 빈 list/dict."""
    from screen_recorder.agent.backends.transformers_backend import TransformersBackend
    backend = TransformersBackend(repo_id="Qwen/test")
    asyncio.run(backend.start_session(system_prompt="ignored", tools={}, model="x"))
    assert backend._openai_tools == []
    assert backend._tool_handlers == {}
    assert backend._tool_strategy == "none"


def test_effective_system_prompt_appends_catalog_in_prompted_mode():
    """prompted 모드 — system prompt 끝에 build_prompted_tool_catalog 결과 합쳐짐."""
    from screen_recorder.agent.backends.transformers_backend import (
        TransformersBackend, _QWEN_SYSTEM_PROMPT,
    )
    backend = TransformersBackend(repo_id="Qwen/test")
    tools_dict = {
        "openai_tools": [
            {"type": "function", "function": {"name": "get_video_state",
                                              "description": "현재 영상",
                                              "parameters": {}}},
        ],
        "tool_handlers": {"get_video_state": lambda a: {}},
        "tool_strategy": "prompted",
    }
    asyncio.run(backend.start_session(system_prompt="ignored", tools=tools_dict, model="x"))

    eff = backend._effective_system_prompt()
    # 기본 Qwen system prompt 유지 + 카탈로그 추가.
    assert _QWEN_SYSTEM_PROMPT in eff
    assert "<tool_call>" in eff
    assert "get_video_state" in eff


def test_effective_system_prompt_unchanged_for_none_strategy():
    """tool_strategy='none' 면 기본 system prompt 그대로 — 카탈로그 미주입."""
    from screen_recorder.agent.backends.transformers_backend import (
        TransformersBackend, _QWEN_SYSTEM_PROMPT,
    )
    backend = TransformersBackend(repo_id="Qwen/test")
    asyncio.run(backend.start_session(system_prompt="ignored", tools={}, model="x"))
    assert backend._effective_system_prompt() == _QWEN_SYSTEM_PROMPT


def test_effective_system_prompt_unchanged_for_official_strategy():
    """tool_strategy='official' 면 카탈로그 미주입 — chat_template 의 tools= 가 처리."""
    from screen_recorder.agent.backends.transformers_backend import (
        TransformersBackend, _QWEN_SYSTEM_PROMPT,
    )
    backend = TransformersBackend(repo_id="Qwen/test")
    tools_dict = {
        "openai_tools": [{"type": "function", "function": {"name": "foo"}}],
        "tool_handlers": {"foo": lambda a: {}},
        "tool_strategy": "official",
    }
    asyncio.run(backend.start_session(system_prompt="ignored", tools=tools_dict, model="x"))
    assert backend._effective_system_prompt() == _QWEN_SYSTEM_PROMPT


def test_send_message_passes_tools_to_apply_chat_template_when_official(
    transformers_mock, qtbot,
):
    """official 모드 — apply_chat_template 호출 시 tools= 인자 전달."""
    from screen_recorder.agent.backends.base import ChatInput
    from screen_recorder.agent.backends.transformers_backend import TransformersBackend

    captured: dict = {}

    class _FakeProcessor:
        def apply_chat_template(self, conv, tools=None, add_generation_prompt=True, tokenize=False):
            captured["conv"] = conv
            captured["tools"] = tools
            return "fake-prompt"

        def __call__(self, **kwargs):
            # processor() 가 inputs dict 처럼 동작 — .to() 체인 가능.
            class _Inputs:
                def to(self, *_a, **_kw): return self
            return _Inputs()

        def batch_decode(self, ids, **kw):
            return [""]

    class _FakeModel:
        device = "cpu"
        dtype = None

        def generate(self, **kw):
            # streamer.end() 호출해 iterate 끝나도록.
            kw["streamer"].end()
            return None

    backend = TransformersBackend(repo_id="Qwen/test")
    backend._model = _FakeModel()
    backend._processor = _FakeProcessor()

    tools_dict = {
        "openai_tools": [
            {"type": "function", "function": {"name": "get_video_state",
                                              "description": "x",
                                              "parameters": {}}},
        ],
        "tool_handlers": {"get_video_state": lambda a: {"ok": True}},
        "tool_strategy": "official",
    }
    asyncio.run(backend.start_session("ignored", tools_dict, "x"))

    # qwen_omni_utils.process_mm_info mock 가 (None, None, None) 반환하도록.
    transformers_mock["qwen_omni_utils"].process_mm_info.return_value = (None, None, None)

    # TextIteratorStreamer mock — iter 가 즉시 끝남 (no chunks).
    class _FakeStreamer:
        def __init__(self, *a, **kw): pass
        def __iter__(self): return iter([])
        def end(self): pass
    transformers_mock["transformers"].TextIteratorStreamer = _FakeStreamer
    transformers_mock["transformers"].StoppingCriteria = object
    transformers_mock["transformers"].StoppingCriteriaList = lambda x: x

    events: list = []
    async def _run():
        await backend.send_message(ChatInput(text="hi"), events.append)
    asyncio.run(_run())

    # apply_chat_template 호출되었고 tools= 가 openai_tools 와 일치.
    assert captured.get("tools") is not None, "tools= 인자 안 전달됨"
    assert captured["tools"] == tools_dict["openai_tools"]


def test_send_message_omits_tools_when_prompted(transformers_mock, qtbot):
    """prompted 모드 — apply_chat_template 에 tools= 안 전달 (system prompt 가 처리)."""
    from screen_recorder.agent.backends.base import ChatInput
    from screen_recorder.agent.backends.transformers_backend import TransformersBackend

    captured: dict = {}

    class _FakeProcessor:
        def apply_chat_template(self, conv, tools=None, add_generation_prompt=True, tokenize=False):
            captured["tools"] = tools
            return "fake-prompt"
        def __call__(self, **kwargs):
            class _Inputs:
                def to(self, *_a, **_kw): return self
            return _Inputs()
        def batch_decode(self, ids, **kw): return [""]

    class _FakeModel:
        device = "cpu"
        dtype = None
        def generate(self, **kw):
            kw["streamer"].end()
            return None

    backend = TransformersBackend(repo_id="Qwen/test")
    backend._model = _FakeModel()
    backend._processor = _FakeProcessor()

    tools_dict = {
        "openai_tools": [{"type": "function", "function": {"name": "foo",
                                                            "description": "x",
                                                            "parameters": {}}}],
        "tool_handlers": {"foo": lambda a: {}},
        "tool_strategy": "prompted",
    }
    asyncio.run(backend.start_session("ignored", tools_dict, "x"))
    transformers_mock["qwen_omni_utils"].process_mm_info.return_value = (None, None, None)
    class _FakeStreamer:
        def __init__(self, *a, **kw): pass
        def __iter__(self): return iter([])
        def end(self): pass
    transformers_mock["transformers"].TextIteratorStreamer = _FakeStreamer
    transformers_mock["transformers"].StoppingCriteria = object
    transformers_mock["transformers"].StoppingCriteriaList = lambda x: x

    async def _run():
        await backend.send_message(ChatInput(text="hi"), lambda _e: None)
    asyncio.run(_run())

    # prompted 모드 — tools= None.
    assert captured.get("tools") is None


def test_send_message_emits_tool_use_event_when_model_outputs_tool_call(transformers_mock):
    """모델 출력에 <tool_call> 있으면 AgentEvent(kind='tool_use') + AgentMessage(role='tool_use') emit.

    회귀 보호: Claude 의 ToolUseBlock 처리 패턴 (chat_panel 의 role='tool_use' 표시) 동등성.

    Note: multi-round 루프 도입 후 stateless _FakeStreamer 를 쓰면 매 라운드마다 같은
    tool_call 을 emit → 무한 루프 (_MAX_TOOL_ROUNDS 까지). generate_count 로 라운드를
    구분해 1차 = tool_call, 2차 = 최종 텍스트.
    """
    from screen_recorder.agent.backends.base import ChatInput, AgentEvent, AgentMessage
    from screen_recorder.agent.backends.transformers_backend import TransformersBackend

    # 모델이 한 chunk 로 tool_call 전체 출력하는 시나리오.
    tool_call_text = '<tool_call>{"name": "get_video_state", "arguments": {}}</tool_call>'
    generate_count = {"n": 0}
    outputs = [tool_call_text, "완료되었습니다."]

    class _FakeProcessor:
        def apply_chat_template(self, conv, tools=None, **kw): return "p"
        def __call__(self, **kw):
            class _Inputs(dict):
                def to(self, *_a, **_kw): return self
            return _Inputs()
        def batch_decode(self, ids, **kw): return [""]

    class _FakeModel:
        device = "cpu"; dtype = None
        def generate(self, **kw):
            generate_count["n"] += 1
            kw["streamer"].end()
            return None

    # streamer iter — 라운드별로 다른 출력. 1차 = tool_call, 2차 = 최종 텍스트.
    class _FakeStreamer:
        def __init__(self, *a, **kw):
            self._fed = [outputs[min(generate_count["n"], len(outputs) - 1)]]
        def __iter__(self): return iter(self._fed)
        def end(self): pass

    transformers_mock["transformers"].TextIteratorStreamer = _FakeStreamer
    transformers_mock["transformers"].StoppingCriteria = object
    transformers_mock["transformers"].StoppingCriteriaList = lambda x: x
    transformers_mock["qwen_omni_utils"].process_mm_info.return_value = (None, None, None)

    backend = TransformersBackend(repo_id="Qwen/test")
    backend._model = _FakeModel()
    backend._processor = _FakeProcessor()

    handler_calls: list = []
    def _handler(args):
        handler_calls.append(args)
        return {"duration_ms": 1000}

    tools_dict = {
        "openai_tools": [{"type": "function", "function": {"name": "get_video_state",
                                                            "description": "x", "parameters": {}}}],
        "tool_handlers": {"get_video_state": _handler},
        "tool_strategy": "prompted",
    }
    asyncio.run(backend.start_session("ignored", tools_dict, "x"))

    events: list = []
    async def _run():
        await backend.send_message(ChatInput(text="영상 상태 알려줘"), events.append)
    asyncio.run(_run())

    # tool_use event 1개 emit (handler 도 호출).
    tool_use_events = [e for e in events if isinstance(e, AgentEvent) and e.kind == "tool_use"]
    assert len(tool_use_events) == 1
    assert "get_video_state" in tool_use_events[0].detail
    # tool_use AgentMessage 도 1개 (Claude 와 동등한 UI 표현).
    tool_use_msgs = [m for m in events if isinstance(m, AgentMessage) and m.role == "tool_use"]
    assert len(tool_use_msgs) == 1
    assert tool_use_msgs[0].tool_name == "get_video_state"


def test_send_message_invokes_handler_and_emits_final_assistant_text(transformers_mock):
    """tool_call → handler 호출 → conversation 에 결과 append → 재 generate → 최종 답변 emit.

    회귀: Claude 의 tool_use + tool_result 흐름을 transformers 도 재현해야 chat_panel UI 가 동일.
    """
    from screen_recorder.agent.backends.base import ChatInput, AgentMessage, AgentEvent
    from screen_recorder.agent.backends.transformers_backend import TransformersBackend

    # 1차 generate: tool_call. 2차 generate: 최종 답변.
    generate_count = {"n": 0}
    outputs = [
        '<tool_call>{"name": "get_video_state", "arguments": {}}</tool_call>',
        "영상 길이는 1초입니다.",
    ]

    class _FakeProcessor:
        def apply_chat_template(self, conv, tools=None, **kw): return "p"
        def __call__(self, **kw):
            class _Inputs(dict):
                def to(self, *_a, **_kw): return self
            return _Inputs()
        def batch_decode(self, ids, **kw): return [""]

    class _FakeStreamer:
        def __init__(self, *a, **kw):
            self._fed = [outputs[generate_count["n"]]]
        def __iter__(self): return iter(self._fed)
        def end(self): pass

    class _FakeModel:
        device = "cpu"; dtype = None
        def generate(self, **kw):
            generate_count["n"] += 1
            kw["streamer"].end()
            return None

    transformers_mock["transformers"].TextIteratorStreamer = _FakeStreamer
    transformers_mock["transformers"].StoppingCriteria = object
    transformers_mock["transformers"].StoppingCriteriaList = lambda x: x
    transformers_mock["qwen_omni_utils"].process_mm_info.return_value = (None, None, None)

    backend = TransformersBackend(repo_id="Qwen/test")
    backend._model = _FakeModel()
    backend._processor = _FakeProcessor()

    handler_calls: list = []
    def _handler(args):
        handler_calls.append(args)
        return {"duration_ms": 1000}

    tools_dict = {
        "openai_tools": [{"type": "function", "function": {"name": "get_video_state",
                                                            "description": "x", "parameters": {}}}],
        "tool_handlers": {"get_video_state": _handler},
        "tool_strategy": "prompted",
    }
    asyncio.run(backend.start_session("ignored", tools_dict, "x"))

    events: list = []
    async def _run():
        await backend.send_message(ChatInput(text="영상 상태?"), events.append)
    asyncio.run(_run())

    # handler 호출됨.
    assert len(handler_calls) == 1
    # generate 2회 — 1차 (tool_call) + 2차 (최종 답변).
    assert generate_count["n"] == 2
    # 최종 assistant 메시지에 답변 포함.
    asst = [m for m in events if isinstance(m, AgentMessage) and m.role == "assistant"]
    final = "".join(m.text for m in asst)
    assert "영상 길이" in final
    # tool_result AgentMessage 도 emit (Claude 와 같은 UI).
    tool_results = [m for m in events if isinstance(m, AgentMessage) and m.role == "tool_result"]
    assert len(tool_results) == 1
