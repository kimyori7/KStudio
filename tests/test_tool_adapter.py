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


def test_parse_tool_calls_hermes_single():
    """단일 <tool_call> 태그 — name + arguments dict 반환."""
    from screen_recorder.agent.backends.tool_adapter import parse_tool_calls
    text = (
        "도구를 호출하겠습니다.\n"
        '<tool_call>{"name": "get_video_state", "arguments": {}}</tool_call>'
    )
    calls = parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_video_state"
    assert calls[0]["arguments"] == {}
    # 호출자가 추적용 ID 부여 — 같은 입력엔 같은 ID, 다른 입력엔 다른 ID.
    assert "id" in calls[0]
    assert calls[0]["id"]   # non-empty.


def test_parse_tool_calls_hermes_multiple():
    """여러 <tool_call> 태그 — 순서 보존."""
    from screen_recorder.agent.backends.tool_adapter import parse_tool_calls
    text = (
        '<tool_call>{"name": "get_video_state", "arguments": {}}</tool_call>\n'
        '<tool_call>{"name": "propose_effect", "arguments": {"type": "cut", "payload": {"in_ms": 0, "out_ms": 1000}}}</tool_call>'
    )
    calls = parse_tool_calls(text)
    assert len(calls) == 2
    assert calls[0]["name"] == "get_video_state"
    assert calls[1]["name"] == "propose_effect"
    assert calls[1]["arguments"]["type"] == "cut"
    assert calls[0]["id"] != calls[1]["id"]


def test_parse_tool_calls_returns_empty_when_no_tags():
    """일반 텍스트 응답 — 빈 list."""
    from screen_recorder.agent.backends.tool_adapter import parse_tool_calls
    assert parse_tool_calls("안녕하세요, 어떻게 도와드릴까요?") == []


def test_parse_tool_calls_skips_malformed_json():
    """JSON parse 실패한 태그는 skip — 다른 valid 태그는 유지.

    회귀 보호: spec 의 "schema 위반 → 재시도" 폴백은 호출자 책임이지만,
    파서 자체가 raise 하면 전체 turn 망함. skip 으로 안전.
    """
    from screen_recorder.agent.backends.tool_adapter import parse_tool_calls
    text = (
        '<tool_call>{"name": broken json}</tool_call>\n'
        '<tool_call>{"name": "get_video_state", "arguments": {}}</tool_call>'
    )
    calls = parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_video_state"


def test_parse_tool_calls_strips_tool_call_tags_from_text():
    """원문에서 <tool_call> 태그 제거된 텍스트 반환 — UI 표시용."""
    from screen_recorder.agent.backends.tool_adapter import strip_tool_call_tags
    text = (
        "도구를 호출하겠습니다.\n"
        '<tool_call>{"name": "get_video_state", "arguments": {}}</tool_call>\n'
        "결과를 보고 답변드릴게요."
    )
    stripped = strip_tool_call_tags(text)
    assert "<tool_call>" not in stripped
    assert "</tool_call>" not in stripped
    assert "도구를 호출하겠습니다." in stripped
    assert "결과를 보고 답변드릴게요." in stripped
