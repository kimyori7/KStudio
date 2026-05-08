"""media_probe — ffprobe 로 영상 파일 길이 조회. 짧은 동기 호출."""
from __future__ import annotations
import json
import logging
import subprocess
from pathlib import Path

_log = logging.getLogger(__name__)


def probe_duration_ms(src: str) -> int:
    """영상 파일의 길이 (ms). 실패 시 0 반환.

    ffprobe -v error -show_entries format=duration -of json <src>
    """
    if not src or not Path(src).exists():
        return 0
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
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
    except Exception:
        _log.exception("probe_duration_ms error")
        return 0
