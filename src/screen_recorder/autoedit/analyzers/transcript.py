"""TranscriptAnalyzer — agent/transcript.py 의 캐시 재사용.

agent 가 채팅에서 한 번 transcribe 했으면 디스크 캐시 hit 으로 즉시.

Note: agent/transcript.Transcriber 의 내부 세그먼트는 start_ms/end_ms (정수 ms) 를 쓰지만
_transcribe() 는 start/end (float 초) 로 정규화해서 반환한다 — mock 과 실 구현 동일 인터페이스.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .base import Analyzer, AnalyzerCancelled


@dataclass
class _Segment:
    """정규화된 세그먼트 — start/end 는 float 초."""
    start: float
    end: float
    text: str


def _transcribe(
    media_path: Path,
    *,
    model_size: str = "base",
    is_cancelled: Callable[[], bool] | None = None,
) -> list[_Segment]:
    """faster-whisper 호출 — 분리해서 테스트에서 mock 가능.

    agent/transcript.Transcriber 를 그대로 재사용해 전사 캐시 hit 가능.
    is_cancelled 전달 → 매 segment 마다 체크해 사용자 취소 즉시 반영.
    반환: start/end (float 초), text 를 가진 객체 리스트.
    """
    from ...agent.transcript import get_transcriber
    t = get_transcriber()
    result = t.transcribe(
        str(media_path),
        model_size=model_size,
        is_cancelled=is_cancelled,
    )
    # result 는 Transcript 객체 — .segments 는 TranscriptSegment(start_ms, end_ms, text)
    return [
        _Segment(
            start=seg.start_ms / 1000.0,
            end=seg.end_ms / 1000.0,
            text=seg.text,
        )
        for seg in result.segments
    ]


class TranscriptAnalyzer(Analyzer):
    name = "자막"
    version = "v1"

    def __init__(self, model_size: str = "base") -> None:
        self._model_size = model_size

    def analyze(
        self,
        media_path: Path,
        *,
        progress: Callable[[float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        if is_cancelled and is_cancelled():
            raise AnalyzerCancelled
        if progress:
            progress(0.1)

        # is_cancelled 를 transcribe 안쪽 segment 루프까지 전파 — 사용자 취소 시
        # whisper iterator 가 즉시 중단되어 다음 segment 추론 안 함.
        try:
            segments = _transcribe(
                media_path,
                model_size=self._model_size,
                is_cancelled=is_cancelled,
            )
        except Exception as e:
            # Transcriber 가 던지는 TranscribeCancelled — autoedit 의 AnalyzerCancelled 로 정규화.
            if type(e).__name__ == "TranscribeCancelled":
                raise AnalyzerCancelled from e
            raise

        if is_cancelled and is_cancelled():
            raise AnalyzerCancelled

        out = []
        for s in segments:
            out.append({
                "in_ms": int(getattr(s, "start", 0.0) * 1000),
                "out_ms": int(getattr(s, "end", 0.0) * 1000),
                "text": str(getattr(s, "text", "")).strip(),
            })

        if progress:
            progress(1.0)
        return {"transcript_segments": out}
