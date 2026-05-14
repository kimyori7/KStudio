"""백워드 호환 shim — 기존 import 경로 유지.

실제 구현은 `agent.tools` 패키지 + `agent.adapter` 로 분리됨 (2026-05-13).
신규 코드는 분리된 경로 직접 import 권장:
    from screen_recorder.agent.tools import VideoTools
    from screen_recorder.agent.adapter import VideoSessionAdapter

이 모듈은 기존 코드와 테스트가 `from agent.tools_video import ...` 로 접근하던 것
을 안 깨도록 re-export. 신규 코드는 사용 X.
"""
from __future__ import annotations

# 공개 API.
from .adapter import VideoSessionAdapter
from .tools import VideoTools, ApplyCallback

# 헬퍼 — 테스트에서 직접 호출하는 _ prefix 함수들.
from .tools._response import (
    text_result as _text_result,
    image_result as _image_result,
    error_result as _error_result,
    no_active_video as _no_active_video,
)
from .tools._format import (
    format_ms_short as _format_ms_short,
    sidecar_summary_text as _sidecar_summary_text,
    segment_summary as _segment_summary,
    effect_summary as _effect_summary,
)

__all__ = [
    "VideoTools", "VideoSessionAdapter", "ApplyCallback",
    "_text_result", "_image_result", "_error_result", "_no_active_video",
    "_format_ms_short", "_sidecar_summary_text",
    "_segment_summary", "_effect_summary",
]
