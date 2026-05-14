"""SceneAnalyzer — PySceneDetect ContentDetector → 씬 시작 지점."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable

from .base import Analyzer, AnalyzerCancelled


def _detect_scenes(media_path: Path, threshold: float = 27.0):
    """PySceneDetect 호출 — 분리해서 mock 가능.

    실제 반환값: list of (FrameTimecode, FrameTimecode) — (scene_start, scene_end).
    PySceneDetect >= 0.6: detect() 는 SceneList (list 의 서브클래스) 반환.
    """
    from scenedetect import detect, ContentDetector
    return detect(str(media_path), ContentDetector(threshold=threshold))


class SceneAnalyzer(Analyzer):
    name = "씬 감지"
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
        scenes = _detect_scenes(media_path)
        if is_cancelled and is_cancelled():
            raise AnalyzerCancelled

        # 첫 씬은 0초 = 영상 시작 (실제 content change 아님). 두 번째부터.
        # PySceneDetect 가 per-scene score 직접 제공 안 함 → 임계값 자체를 score 로 기록.
        # filter 가 scene_sensitivity 와 비교 (기본 30) → 통과 / 제외.
        out: list[tuple[int, float]] = []
        for i, (start, _end) in enumerate(scenes):
            if i == 0:
                continue
            ms = int(start.get_seconds() * 1000)
            out.append((ms, 30.0))

        if progress:
            progress(1.0)
        return {"scene_changes": out}
