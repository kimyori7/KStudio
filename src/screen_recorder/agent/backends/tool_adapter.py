"""MCP (Claude) ↔ OpenAI (Qwen / Hermes) 도구 schema 변환 + tool_call 파싱.

Claude SDK 는 MCP 형식 도구 정의 + auto-invocation. Qwen 계열은 OpenAI function
calling 형식만 받음 + 응답에 `<tool_call>{json}</tool_call>` 태그로 출력. 어댑터가
양쪽 변환 + 파싱 담당. Qwen2.5-Omni 같이 chat_template 에 tool 지원 없는 모델도
같은 출력 형식 사용 (시스템 프롬프트로 강제) — 파서 동일.

순수 함수 모음 — Qt / asyncio 의존 없음.
"""
from __future__ import annotations

import json
import re
from typing import Any


# KStudio MCP 도구 prefix — VideoTools 의 mcp_server 이름과 일치.
_MCP_PREFIX = "mcp__kstudio_video__"


def mcp_to_openai_tools(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Claude MCP 도구 정의 list → OpenAI tools list.

    각 입력 dict 는 {"name": "mcp__..._<name>", "description": str, "input_schema": dict}.
    출력은 {"type": "function", "function": {"name", "description", "parameters"}}.
    """
    out: list[dict[str, Any]] = []
    for t in mcp_tools:
        name = mcp_to_openai_name(t.get("name", ""))
        params = t.get("input_schema") or {
            "type": "object", "properties": {}, "required": [],
        }
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": t.get("description", ""),
                "parameters": params,
            },
        })
    return out


def mcp_to_openai_name(name: str) -> str:
    """'mcp__kstudio_video__get_video_state' → 'get_video_state'. Idempotent."""
    if name.startswith(_MCP_PREFIX):
        return name[len(_MCP_PREFIX):]
    return name


def openai_to_mcp_name(name: str) -> str:
    """역변환 — Qwen 출력 name → MCP 도구 이름. Idempotent."""
    if name.startswith(_MCP_PREFIX):
        return name
    return _MCP_PREFIX + name
