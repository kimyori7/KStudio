"""5배속 재생 시 점진적 UI 정지 진단용 카운터.

환경변수 `KSTUDIO_PERF_DIAG=1` 일 때만 MainWindow 가 5초 주기로 mem/threads/
ffmpeg_procs 와 함께 이 카운터를 dump. 비활성화 시 inc() 호출은 거의 무료
(int 비교 1회).
"""
from __future__ import annotations
import os


_ENABLED: bool = os.environ.get("KSTUDIO_PERF_DIAG") == "1"

_COUNTERS: dict[str, int] = {
    "combined_pos": 0,   # SegmentPlaybackController.combined_position_changed emit
    "raw_pos": 0,        # PlayerWidget.position_changed emit (raw QMediaPlayer)
    "frame_changed": 0,  # _VideoSurface.videoFrameChanged 도착
}


def enabled() -> bool:
    return _ENABLED


def inc(key: str) -> None:
    """카운터 증가 — 비활성 시 즉시 반환."""
    if not _ENABLED:
        return
    if key in _COUNTERS:
        _COUNTERS[key] += 1


def snapshot_and_reset() -> dict[str, int]:
    """현재 카운터 스냅샷을 반환하고 0 으로 리셋."""
    snap = dict(_COUNTERS)
    for k in _COUNTERS:
        _COUNTERS[k] = 0
    return snap
