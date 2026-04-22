"""ffmpeg.exe 위치 탐색."""
from __future__ import annotations
from pathlib import Path
import shutil
import sys

_BUNDLED_PATHS: list[Path] = [
    Path(sys.argv[0]).parent / "bin" / "ffmpeg.exe",
    Path(__file__).resolve().parent.parent.parent.parent / "bin" / "ffmpeg.exe",
]

_cached: Path | None = None
_cached_set = False


def find_ffmpeg(use_cache: bool = True) -> Path | None:
    """PATH 우선, 없으면 동봉 위치 탐색. 결과를 캐시."""
    global _cached, _cached_set
    if use_cache and _cached_set:
        return _cached

    on_path = shutil.which("ffmpeg")
    if on_path:
        result: Path | None = Path(on_path)
    else:
        result = next((p for p in _BUNDLED_PATHS if p.exists()), None)

    _cached = result
    _cached_set = True
    return result


def reset_cache() -> None:
    global _cached, _cached_set
    _cached = None
    _cached_set = False
