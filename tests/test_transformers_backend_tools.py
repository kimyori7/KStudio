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
