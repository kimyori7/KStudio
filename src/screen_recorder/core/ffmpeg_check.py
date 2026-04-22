"""ffmpeg.exe 위치 탐색."""
from __future__ import annotations
from pathlib import Path
import shutil
import sys

def _bundled_paths() -> list[Path]:
    paths = [
        Path(sys.argv[0]).parent / "bin" / "ffmpeg.exe",              # exe 옆 bin
        Path(__file__).resolve().parent.parent.parent.parent / "bin" / "ffmpeg.exe",  # 소스 실행
    ]
    # PyInstaller onedir: _internal/bin/ffmpeg.exe
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        paths.append(exe_dir / "_internal" / "bin" / "ffmpeg.exe")
        # PyInstaller onefile 또는 기타: sys._MEIPASS
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            paths.append(Path(meipass) / "bin" / "ffmpeg.exe")
    return paths


_BUNDLED_PATHS: list[Path] = _bundled_paths()

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
