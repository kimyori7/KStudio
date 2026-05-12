"""media_probe — ffprobe 로 영상 파일 길이 조회. 짧은 동기 호출.

ffprobe 경로: PATH 우선, 없으면 동봉본 (`bin/ffprobe.exe` — find_ffmpeg 와
같은 디렉터리 패턴). PATH 에만 의존하면 소스 실행 시 ffprobe 못 찾아 길이 0
반환 → drag-drop append 한 영상이 0초 segment 로 들어가 사실상 미반영되는
회귀.
"""
from __future__ import annotations
import json
import logging
import shutil
import subprocess
from pathlib import Path

from ..core.ffmpeg_check import find_ffmpeg

_log = logging.getLogger(__name__)


def _find_ffprobe() -> str:
    """ffprobe 경로. PATH 우선, 없으면 ffmpeg.exe 옆 ffprobe.exe."""
    on_path = shutil.which("ffprobe")
    if on_path:
        return on_path
    ff = find_ffmpeg()
    if ff is not None:
        cand = ff.parent / ("ffprobe.exe" if ff.name.endswith(".exe") else "ffprobe")
        if cand.exists():
            return str(cand)
    return "ffprobe"   # 최후의 폴백 (실패하면 0 반환)


def has_audio_stream(src: str) -> bool:
    """ffprobe 로 src 에 audio stream 이 있는지 확인.

    실패 시 (파일 없거나 ffprobe 미설치) True 로 낙관 반환 — 실제 ffmpeg 실행
    이 더 정확하게 판단. 진짜 audio 없는 영상은 ffprobe 가 정확히 False 로
    응답 → export_pipeline 이 audio chain 우회.

    화면 녹화 (마이크 입력 없음) 등은 audio stream 자체가 없어 ffmpeg filter
    의 `[idx:a]` 가 "matches no streams" 로 export 실패 → 이 검사로 사전 회피.
    """
    if not src or not Path(src).exists():
        return True   # 파일 없으면 ffprobe 못 함 — 낙관 (테스트 가짜 경로 호환).
    try:
        result = subprocess.run(
            [
                _find_ffprobe(), "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=codec_type",
                "-of", "json", src,
            ],
            capture_output=True, timeout=5,
        )
        if result.returncode != 0:
            return True   # ffprobe 실패 — 낙관.
        data = json.loads(result.stdout.decode("utf-8", "replace"))
        return bool(data.get("streams"))
    except Exception:
        return True


def probe_duration_ms(src: str) -> int:
    """영상 파일의 길이 (ms). 실패 시 0 반환.

    ffprobe -v error -show_entries format=duration -of json <src>
    """
    if not src or not Path(src).exists():
        return 0
    try:
        result = subprocess.run(
            [
                _find_ffprobe(), "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json", src,
            ],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            _log.warning("ffprobe failed: %s", result.stderr.decode("utf-8", "replace"))
            return 0
        data = json.loads(result.stdout.decode("utf-8", "replace"))
        dur_s = float(data.get("format", {}).get("duration", 0))
        return int(round(dur_s * 1000))
    except FileNotFoundError:
        _log.warning("ffprobe not found on PATH and no bundled ffprobe.exe")
        return 0
    except Exception:
        _log.exception("probe_duration_ms error")
        return 0
