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
