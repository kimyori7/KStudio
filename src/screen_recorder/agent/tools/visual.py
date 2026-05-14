"""비주얼 도구 2개 — ffmpeg subprocess + PIL 합성.

- `get_frame_at(ms, width=320)`        — 특정 시점 한 프레임 PNG.
- `get_timeline_strip(start, end, n)`  — 균일 간격 썸네일 가로 합성 PNG.

ffmpeg 단발 호출이 thread-safe + 결정론적. PlayerWidget 의 UI-thread 마샬링 우회.
"""
from __future__ import annotations

import logging
from typing import Optional

from claude_agent_sdk import tool

from ..adapter import VideoSessionAdapter
from ..frame_extractor import composite_timeline_strip, extract_frame_png
from ._format import format_ms_short
from ._response import error_result, image_result, no_active_video

_log = logging.getLogger(__name__)


VISUAL_TOOL_NAMES = (
    "get_frame_at",
    "get_timeline_strip",
)


def make_visual_tools(
    adapter: VideoSessionAdapter,
    ffmpeg_path: Optional[str],
) -> list:
    @tool(
        "get_frame_at",
        "영상의 특정 시점(ms) 한 프레임을 이미지로 반환. "
        "Claude 가 그 순간의 화면 내용을 직접 보고 판단할 때 사용. 예: '12.5초 시점에 누가 화면에 있어?'",
        {"ms": int, "width": int},
    )
    async def get_frame_at(args: dict) -> dict:
        if not adapter.has_active_video():
            return no_active_video()
        if not ffmpeg_path:
            return error_result("ffmpeg 경로 미설정 — 비주얼 도구 비활성.")
        src = adapter.source_path()
        if not src:
            return error_result("활성 영상의 소스 경로가 없습니다.")
        ms = int(args.get("ms", 0))
        width = int(args.get("width") or 320)
        try:
            png = extract_frame_png(src, ms, ffmpeg_path, width=width)
        except Exception as exc:
            _log.warning("get_frame_at failed: %s", exc)
            return error_result(f"프레임 추출 실패: {exc}")
        return image_result(png, caption=f"{src} @ {ms}ms (width={width})")

    @tool(
        "get_timeline_strip",
        "[start_ms, end_ms] 범위에서 균일 간격 n 개 썸네일을 가로로 합친 PNG 1장. "
        "범위 전체의 시각적 흐름을 한 눈에 파악할 때 사용 — 토큰 효율이 매우 좋음. "
        "예: '전체 영상이 어떻게 흘러가?' / '20~30초 구간 어떻게 생겼어?'",
        {"start_ms": int, "end_ms": int, "n": int},
    )
    async def get_timeline_strip(args: dict) -> dict:
        if not adapter.has_active_video():
            return no_active_video()
        if not ffmpeg_path:
            return error_result("ffmpeg 경로 미설정 — 비주얼 도구 비활성.")
        src = adapter.source_path()
        if not src:
            return error_result("활성 영상의 소스 경로가 없습니다.")
        dur = adapter.duration_ms()
        start = max(0, int(args.get("start_ms", 0)))
        end = min(dur, int(args.get("end_ms", dur)))
        n = max(1, min(16, int(args.get("n") or 8)))
        if end <= start:
            return error_result(f"잘못된 범위 — start_ms({start}) >= end_ms({end}).")
        try:
            png = composite_timeline_strip(src, start, end, n, ffmpeg_path)
        except Exception as exc:
            _log.warning("get_timeline_strip failed: %s", exc)
            return error_result(f"타임라인 strip 합성 실패: {exc}")
        caption = (
            f"timeline strip: {format_ms_short(start)}~{format_ms_short(end)}, "
            f"n={n} thumbnails"
        )
        return image_result(png, caption=caption)

    return [get_frame_at, get_timeline_strip]
