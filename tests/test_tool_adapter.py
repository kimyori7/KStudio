"""Tool adapter — MCP ↔ OpenAI tools schema 변환 + Qwen tool_call 파싱."""
from __future__ import annotations

import pytest


def test_mcp_to_openai_tools_strips_prefix_and_renames_schema_field():
    """MCP 도구 dict → OpenAI 도구 dict.

    - name 의 'mcp__kstudio_video__' prefix 제거.
    - input_schema → parameters.
    - 최상위 type='function' + function 래핑.
    """
    from screen_recorder.agent.backends.tool_adapter import mcp_to_openai_tools

    mcp_tools = [
        {
            "name": "mcp__kstudio_video__get_video_state",
            "description": "현재 영상 상태",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "mcp__kstudio_video__propose_effect",
            "description": "효과 제안",
            "input_schema": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["type", "payload"],
            },
        },
    ]
    out = mcp_to_openai_tools(mcp_tools)

    assert len(out) == 2
    assert out[0] == {
        "type": "function",
        "function": {
            "name": "get_video_state",
            "description": "현재 영상 상태",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
    assert out[1]["function"]["name"] == "propose_effect"
    assert out[1]["function"]["parameters"]["required"] == ["type", "payload"]


def test_mcp_to_openai_name_only():
    """단일 이름 변환 — prefix 제거."""
    from screen_recorder.agent.backends.tool_adapter import mcp_to_openai_name
    assert mcp_to_openai_name("mcp__kstudio_video__get_video_state") == "get_video_state"
    assert mcp_to_openai_name("get_video_state") == "get_video_state"   # 이미 변환됨 — idempotent.


def test_openai_to_mcp_name_only():
    """역변환 — Qwen 출력 → MCP 도구 호출 이름."""
    from screen_recorder.agent.backends.tool_adapter import openai_to_mcp_name
    assert openai_to_mcp_name("get_video_state") == "mcp__kstudio_video__get_video_state"
    # 이미 prefix 있으면 그대로 (idempotent).
    assert openai_to_mcp_name("mcp__kstudio_video__get_video_state") == "mcp__kstudio_video__get_video_state"


def test_mcp_to_openai_tools_handles_missing_input_schema():
    """input_schema 없는 도구도 graceful — empty object schema 로 처리."""
    from screen_recorder.agent.backends.tool_adapter import mcp_to_openai_tools
    mcp_tools = [{"name": "mcp__kstudio_video__foo", "description": "bar"}]
    out = mcp_to_openai_tools(mcp_tools)
    assert out[0]["function"]["parameters"] == {"type": "object", "properties": {}, "required": []}
