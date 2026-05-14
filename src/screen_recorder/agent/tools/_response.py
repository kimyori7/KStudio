"""MCP 도구 응답 빌더 — text / image / error.

MCP 응답 표준 포맷:
    {"content": [{"type": "text"|"image", ...}, ...], "isError": bool?}
"""
from __future__ import annotations

import base64
import json
from typing import Any, Optional


def no_active_video() -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": "활성 영상 탭이 없습니다. 영상을 먼저 열어주세요."}
        ],
        "isError": True,
    }


def text_result(payload: Any) -> dict[str, Any]:
    """JSON-직렬화 가능한 dict/list 를 indent=2 텍스트로 반환."""
    return {"content": [
        {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
    ]}


def image_result(png_bytes: bytes, caption: Optional[str] = None) -> dict[str, Any]:
    """PNG bytes → base64 이미지 응답. caption 동반 시 텍스트 블록 먼저."""
    data_b64 = base64.b64encode(png_bytes).decode("ascii")
    content: list[dict[str, Any]] = [
        {"type": "image", "data": data_b64, "mimeType": "image/png"}
    ]
    if caption:
        content.insert(0, {"type": "text", "text": caption})
    return {"content": content}


def error_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": True}
