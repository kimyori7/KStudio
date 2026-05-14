"""자막 도구 3개 — Phase D.

- `transcribe_video(model_size?)` — 영상 전체 전사 (동기, 캐시 저장).
- `get_transcript_range(start_ms, end_ms)` — 캐시에서 시간 슬라이스 반환.
- `get_transcript_status()` — 캐시 존재 여부 + 모델 다운로드 상태.

설계 (advisor 권고):
- 모든 자막 호출은 캐시 우선. 캐시 miss 시 transcribe_video 명시 호출 필요.
- 자동 백그라운드 trigger 안 함 — 사용자가 명시적으로 "자막 뽑아줘" 시점 통제.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from pathlib import Path
from typing import Callable, Optional, Protocol

from claude_agent_sdk import tool

from ..adapter import VideoSessionAdapter
from ..transcript import (
    Transcript, VALID_MODEL_SIZES, WHISPER_SIZE_MB,
    get_transcriber, is_model_cached,
    load_transcript, save_transcript, transcript_path_for,
)
from ._response import error_result, no_active_video, text_result


# 다운로드 콜백 시그니처 — UI 측이 사용자 동의 카드를 표시하고 처리.
DownloadCallback = Callable[[str, concurrent.futures.Future], None]

_log = logging.getLogger(__name__)


TRANSCRIPT_TOOL_NAMES = (
    "transcribe_video",
    "get_transcript_range",
    "get_transcript_status",
    "download_whisper_model",
)


class TranscriptContext(Protocol):
    """transcript 도구가 캐시 위치 + 모델 크기 결정에 사용."""

    def sidecar_dir(self) -> Path: ...
    def source_hash(self) -> Optional[str]: ...
    def default_model_size(self) -> str: ...


def make_transcript_tools(
    adapter: VideoSessionAdapter,
    ctx: TranscriptContext,
    on_download: Optional[DownloadCallback] = None,
) -> list:
    @tool(
        "get_transcript_status",
        "현재 영상의 자막 캐시 상태 — 캐시 있음/없음 + 사용된 모델 + segment 개수. "
        "사용자가 '자막 있어?' 묻거나 transcribe_video 전에 사전 확인.",
        {},
    )
    async def get_transcript_status(args: dict) -> dict:
        if not adapter.has_active_video():
            return no_active_video()
        src = adapter.source_path()
        h = ctx.source_hash()
        if not src or not h:
            return error_result("영상 hash 가 없습니다 — 영상 로드 후 다시 시도.")
        path = transcript_path_for(ctx.sidecar_dir(), Path(src), h)
        t = load_transcript(path)
        default_size = ctx.default_model_size()
        return text_result({
            "transcript_cached": t is not None,
            "model_size_cached": t.model_size if t else None,
            "language": t.language if t else None,
            "n_segments": len(t.segments) if t else 0,
            "default_model_size": default_size,
            "default_model_downloaded": is_model_cached(default_size),
        })

    @tool(
        "transcribe_video",
        "현재 영상 전체를 자막으로 변환 (faster-whisper, 동기). "
        "결과는 디스크 캐시 → 다음부터 get_transcript_range 로 빠르게 조회. "
        "model_size 미지정 시 설정값 (기본 'base'). "
        "**중요**: 모델이 캐시에 없으면 거부 — 먼저 download_whisper_model 로 사용자 동의 받기. "
        "1시간 영상 base 기준 ~1~2분 소요. 작업 중엔 다른 도구 호출 차단.",
        {"model_size": str, "language": str},
    )
    async def transcribe_video(args: dict) -> dict:
        if not adapter.has_active_video():
            return no_active_video()
        src = adapter.source_path()
        h = ctx.source_hash()
        if not src or not h:
            return error_result("영상 소스/hash 가 없습니다.")
        model_size = str(args.get("model_size") or ctx.default_model_size())
        if model_size not in VALID_MODEL_SIZES:
            return error_result(
                f"잘못된 모델 크기: {model_size}. 가능: {', '.join(VALID_MODEL_SIZES)}"
            )
        # 모델 캐시 사전 확인 — 자동 다운로드 방지 (사용자 명시 동의 필요).
        if not is_model_cached(model_size):
            size_mb = WHISPER_SIZE_MB.get(model_size, "?")
            return error_result(
                f"Whisper '{model_size}' 모델 미설치 (~{size_mb}MB 필요). "
                f"사용자 동의를 받은 뒤 download_whisper_model('{model_size}') 를 먼저 호출하세요."
            )
        language = args.get("language") or "ko"
        try:
            transcriber = get_transcriber()
            t = transcriber.transcribe(src, model_size=model_size, language=str(language))
            t.source_hash = h
            cache_path = transcript_path_for(ctx.sidecar_dir(), Path(src), h)
            save_transcript(cache_path, t)
        except Exception as exc:
            _log.exception("transcribe_video failed")
            return error_result(f"전사 실패: {exc}")
        return text_result({
            "ok": True,
            "model_size": t.model_size,
            "language": t.language,
            "duration_ms": t.duration_ms,
            "n_segments": len(t.segments),
            "cache_path": str(cache_path),
        })

    @tool(
        "get_transcript_range",
        "지정 시간 구간 [start_ms, end_ms] 의 자막 segment 들 반환. "
        "캐시 miss (transcribe_video 안 함) 면 에러 — 먼저 transcribe_video 호출 안내. "
        "Claude 가 영상 내용을 '읽고' 편집 결정할 때 핵심 입력.",
        {"start_ms": int, "end_ms": int},
    )
    async def get_transcript_range(args: dict) -> dict:
        if not adapter.has_active_video():
            return no_active_video()
        src = adapter.source_path()
        h = ctx.source_hash()
        if not src or not h:
            return error_result("영상 소스/hash 가 없습니다.")
        cache_path = transcript_path_for(ctx.sidecar_dir(), Path(src), h)
        t = load_transcript(cache_path)
        if t is None:
            return error_result(
                "자막 캐시 없음. 먼저 transcribe_video() 를 호출해 영상 전체를 전사하세요."
            )
        start = int(args.get("start_ms", 0))
        end = int(args.get("end_ms", t.duration_ms))
        segs = t.segments_in_range(start, end)
        return text_result({
            "range": {"start_ms": start, "end_ms": end},
            "model_size": t.model_size,
            "language": t.language,
            "n_segments": len(segs),
            "segments": [s.to_dict() for s in segs],
        })

    @tool(
        "download_whisper_model",
        "Whisper 모델 다운로드 — **사용자 동의 카드를 통해서만 실행됨**. "
        "사용자가 '자막 받자'·'좋아 다운로드해' 같은 명시 동의 후에만 호출. "
        "model_size: tiny(~39MB) / base(~74MB) / small(~244MB) / medium(~769MB) / large-v3(~1550MB). "
        "이미 캐시돼 있으면 즉시 반환. 미설치 시 채팅 카드로 사용자 [✓다운로드]/[✗취소] 받음.",
        {"model_size": str},
    )
    async def download_whisper_model(args: dict) -> dict:
        model_size = str(args.get("model_size") or ctx.default_model_size())
        if model_size not in VALID_MODEL_SIZES:
            return error_result(
                f"잘못된 모델 크기: {model_size}. 가능: {', '.join(VALID_MODEL_SIZES)}"
            )
        if is_model_cached(model_size):
            return text_result({
                "ok": True,
                "model_size": model_size,
                "already_cached": True,
            })
        if on_download is None:
            return error_result(
                "다운로드 콜백 미설정 — UI 와 wiring 안 됨. 사용자에게 직접 환경설정에서 받도록 안내."
            )
        # UI 측에 카드 표시 요청 → 사용자 클릭 후 future 해결.
        fut: concurrent.futures.Future = concurrent.futures.Future()
        try:
            on_download(model_size, fut)
        except Exception as exc:
            _log.exception("download_whisper_model: dispatch failed")
            return error_result(f"다운로드 디스패치 실패: {exc}")
        try:
            result = await asyncio.wrap_future(fut)
        except Exception as exc:
            _log.exception("download_whisper_model: future failed")
            return error_result(f"다운로드 실행 실패: {exc}")
        return text_result(result)

    return [
        transcribe_video,
        get_transcript_range,
        get_transcript_status,
        download_whisper_model,
    ]
