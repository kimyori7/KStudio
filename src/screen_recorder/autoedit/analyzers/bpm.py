"""BPMAnalyzer — librosa.beat 으로 음악 비트 시점 추출.

활용: filter 에서 transcript 자막의 in_ms 를 가장 가까운 비트로 snap.
신뢰도는 per-beat 가 아닌 전역 — librosa 가 tempo 안정적이면 0.7 고정.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable

from .base import Analyzer, AnalyzerCancelled


def _beat_track(media_path: Path) -> tuple[list[float], float]:
    """librosa 호출 — mock 가능 경계."""
    import librosa  # type: ignore
    y, sr = librosa.load(str(media_path), sr=None, mono=True)
    tempo, beats_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beats_frames, sr=sr)
    return list(beat_times), float(tempo)


class BPMAnalyzer(Analyzer):
    name = "BPM"
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
        beat_times, tempo = _beat_track(media_path)
        if is_cancelled and is_cancelled():
            raise AnalyzerCancelled

        beats: list[tuple[int, float]] = [
            (int(t * 1000), 0.7) for t in beat_times
        ]
        if progress:
            progress(1.0)
        return {"beats": beats}
