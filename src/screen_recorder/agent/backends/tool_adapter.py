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


# <tool_call> ... </tool_call> 정규식. DOTALL — JSON 안에 줄바꿈 가능.
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def parse_tool_calls(text: str) -> list[dict[str, Any]]:
    """Qwen / Hermes 응답 텍스트에서 <tool_call>{...}</tool_call> 추출.

    각 결과 dict: {"id": "tu_<n>", "name": str, "arguments": dict}.
    JSON parse 실패한 태그는 skip (회귀 보호 — 한 turn 의 다른 도구 호출은 유지).

    'id' 는 호출자가 tool_result 회신 시 매칭용. tu_0, tu_1, ... 순차 부여.
    """
    calls: list[dict[str, Any]] = []
    for idx, match in enumerate(_TOOL_CALL_RE.finditer(text)):
        raw = match.group(1).strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # 다음 valid 태그 시도 — turn 전체 망치지 않도록.
            continue
        if not isinstance(parsed, dict):
            continue
        name = parsed.get("name")
        args = parsed.get("arguments", {})
        if not isinstance(name, str) or not isinstance(args, dict):
            continue
        calls.append({"id": f"tu_{idx}", "name": name, "arguments": args})
    return calls


def strip_tool_call_tags(text: str) -> str:
    """<tool_call>...</tool_call> 태그를 텍스트에서 제거 — UI 표시용 (사용자에겐 JSON 가림)."""
    return _TOOL_CALL_RE.sub("", text).strip()


def build_prompted_tool_catalog(openai_tools: list[dict[str, Any]]) -> str:
    """OpenAI tools list → system prompt 추가용 카탈로그 텍스트.

    chat_template 이 tools= 미지원인 모델 (Qwen2.5-Omni 등) 에서 사용 — 시스템 프롬프트에
    이 텍스트를 합쳐 모델이 도구 알게 + Hermes 형식 출력 강제. parse_tool_calls 가
    같은 출력 형식 파싱.
    """
    if not openai_tools:
        return ""
    lines: list[str] = [
        "",
        "## 사용 가능한 도구",
        "",
        "다음 도구들을 호출할 수 있습니다. 도구가 필요하면 응답 안에 정확히 다음 형식으로 출력하세요:",
        "",
        '<tool_call>{"name": "도구이름", "arguments": {"인자": "값"}}</tool_call>',
        "",
        "도구 정의:",
    ]
    for t in openai_tools:
        fn = t.get("function") or {}
        name = fn.get("name", "?")
        desc = fn.get("description", "")
        params = fn.get("parameters", {})
        lines.append(f"- **{name}**: {desc}")
        # 파라미터 스키마는 한 줄 JSON 으로 — 컨텍스트 절약.
        lines.append(f"  parameters: {json.dumps(params, ensure_ascii=False)}")
    lines.append("")
    lines.append("도구 호출이 불필요하면 일반 텍스트로 답하세요.")
    return "\n".join(lines)


def build_tool_result_message(tool_use_id: str, result: Any) -> dict[str, Any]:
    """tool result → conversation 의 한 메시지 (Qwen 컨벤션: user role + <tool_response>).

    Hermes 정식 + prompted 시뮬레이션 양쪽 동일 — Qwen 이 다음 generate 에서 이
    텍스트 보고 최종 응답 생성. result 가 dict 면 JSON 문자열화, string 이면 그대로.
    """
    if isinstance(result, str):
        body = result
    else:
        try:
            body = json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            body = str(result)
    return {
        "role": "user",
        "content": f"<tool_response id=\"{tool_use_id}\">\n{body}\n</tool_response>",
    }
