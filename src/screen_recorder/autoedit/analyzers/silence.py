"""SilenceAnalyzer — faster-whisper VAD 결과로 무음 구간 추출.

VAD 가 발견한 음성 구간의 보충 = 무음. 임계값 적용 없음 — filter.py 가 처리.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Callable

from .base import Analyzer, AnalyzerCancelled


def _detect_voice_intervals(
    media_path: Path,
    *,
    model_size: str = "tiny",
    cpu_threads: int | None = None,
) -> tuple[list[tuple[float, float]], float]:
    """faster-whisper VAD 호출 → (음성 [(start_s, end_s)], 영상 길이 초) 반환.

    분리된 함수 — 테스트에서 mock 가능.
    """
    from faster_whisper import WhisperModel  # type: ignore
    threads = cpu_threads if cpu_threads is not None else max(1, (os.cpu_count() or 2) // 2)
    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=threads)
    segments, info = model.transcribe(
        str(media_path),
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 200},
        without_timestamps=False,
        language=None,
    )
    voice = [(s.start, s.end) for s in segments]
    duration = float(info.duration or 0.0)
    return voice, duration


class SilenceAnalyzer(Analyzer):
    name = "무음컷"
    version = "v1"

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
        voice_s, duration_s = _detect_voice_intervals(media_path)
        if is_cancelled and is_cancelled():
            raise AnalyzerCancelled
        if progress:
            progress(0.8)

        silence: list[tuple[int, int]] = []
        cursor = 0.0
        for start, end in sorted(voice_s):
            if start > cursor:
                silence.append((int(cursor * 1000), int(start * 1000)))
            cursor = max(cursor, end)
        if duration_s > cursor:
            silence.append((int(cursor * 1000), int(duration_s * 1000)))

        if progress:
            progress(1.0)
        return {"silence_segments": silence}
