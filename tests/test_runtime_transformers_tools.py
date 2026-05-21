"""AgentRuntime 가 transformers backend 에 올바른 tools_dict 전달하는지 검증."""
from __future__ import annotations

from unittest.mock import MagicMock


def test_runtime_builds_transformers_tools_dict_on_qwen_set_model(tmp_path):
    """set_model('qwen25-7b-instruct') 후 backend.start_session 의 tools 인자가
    {"openai_tools", "tool_handlers", "tool_strategy"} 형식 + Qwen Instruct 는 official."""
    from screen_recorder.agent.runtime import AgentRuntime

    vt = MagicMock()
    vt.plan_gate = MagicMock(return_value=MagicMock())
    vt.mcp_server = MagicMock(return_value=MagicMock())
    vt.tool_names = MagicMock(return_value=["mcp__kstudio_video__get_video_state"])
    vt.openai_tools_and_handlers = MagicMock(return_value=(
        [{"type": "function", "function": {"name": "get_video_state",
                                           "description": "x", "parameters": {}}}],
        {"get_video_state": lambda a: {"ok": True}},
    ))

    rt = AgentRuntime(video_tools=vt, model="qwen25-7b-instruct", cwd=tmp_path)
    # _create_backend + _tools_dict 검증.
    # set_model 호출하면 backend factory + tools_dict 재계산.
    rt._build_tools_dict()  # 새 메서드 — backend runtime 에 따라 분기.
    td = rt._tools_dict
    # transformers backend 라 OpenAI 키 존재.
    assert "openai_tools" in td
    assert "tool_handlers" in td
    assert td["tool_strategy"] == "official"


def test_runtime_builds_claude_tools_dict_for_claude_model(tmp_path):
    """claude 모델 — 기존 {"mcp_server", "allowed_tools"} 형식 유지 (회귀 보호)."""
    from screen_recorder.agent.runtime import AgentRuntime

    vt = MagicMock()
    vt.plan_gate = MagicMock(return_value=MagicMock())
    vt.mcp_server = MagicMock(return_value=MagicMock())
    vt.tool_names = MagicMock(return_value=["mcp__kstudio_video__get_video_state"])

    rt = AgentRuntime(video_tools=vt, model="claude-sonnet-4-6", cwd=tmp_path)
    rt._build_tools_dict()
    td = rt._tools_dict
    assert "mcp_server" in td
    assert "allowed_tools" in td
    assert "openai_tools" not in td


def test_runtime_transformers_tools_dict_for_omni_uses_prompted_strategy(tmp_path):
    """Qwen2.5-Omni — tool_strategy='prompted'."""
    from screen_recorder.agent.runtime import AgentRuntime

    vt = MagicMock()
    vt.plan_gate = MagicMock(return_value=MagicMock())
    vt.mcp_server = MagicMock(return_value=MagicMock())
    vt.tool_names = MagicMock(return_value=[])
    vt.openai_tools_and_handlers = MagicMock(return_value=([], {}))

    rt = AgentRuntime(video_tools=vt, model="qwen25-omni-7b", cwd=tmp_path)
    rt._build_tools_dict()
    assert rt._tools_dict["tool_strategy"] == "prompted"
