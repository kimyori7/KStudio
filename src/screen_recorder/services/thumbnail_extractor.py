"""ThumbnailExtractor — segment 시작 프레임 1장을 ffmpeg 로 추출 + LRU 캐시.

- 동기 API (`extract_sync`) 와 캐시 조회 API (`get_or_none`).
- 비동기 호출은 ThumbnailService (thumbnail_worker.py) 에서 QThreadPool 로 감쌈.
- src 가 빈 문자열이거나 파일 없으면 None.
"""
from __future__ import annotations
import logging
import subprocess
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QImage


_log = logging.getLogger(__name__)
_THUMB_W = 96
_THUMB_H = 54


class ThumbnailExtractor:
    """LRU 캐시 + ffmpeg 1프레임 추출.

    UI 스레드에서 캐시 조회만 하고 실제 추출은 호출자가 백그라운드 처리 (Service).
    """

    def __init__(self, cache_size: int = 100) -> None:
        self._cache: "OrderedDict[tuple[str, int], QImage]" = OrderedDict()
        self._cache_size = cache_size

    def get_or_none(self, src: str, ms: int) -> tuple[Optional[QImage], bool]:
        """캐시 조회만. 결과: (QImage 또는 None, was_cached: bool)."""
        key = (src, int(ms))
        if key in self._cache:
            self._cache.move_to_end(key)   # LRU touch
            return self._cache[key], True
        return None, False

    def extract_sync(self, src: str, ms: int) -> Optional[QImage]:
        """ffmpeg 동기 호출 → QImage 반환. 실패 시 None.

        호출자는 UI 스레드 차단을 피하기 위해 QtConcurrent / threading 으로 감쌀 것.
        """
        cached, was = self.get_or_none(src, ms)
        if was:
            return cached
        if not src or not Path(src).exists():
            return None
        out_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".png", delete=False
            ) as tmp:
                out_path = tmp.name
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", f"{ms / 1000.0:.3f}",
                "-i", src,
                "-frames:v", "1",
                "-vf", (
                    f"scale={_THUMB_W}:{_THUMB_H}:force_original_aspect_ratio=decrease,"
                    f"pad={_THUMB_W}:{_THUMB_H}:(ow-iw)/2:(oh-ih)/2:black"
                ),
                out_path,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            if result.returncode != 0:
                _log.warning(
                    "ffmpeg thumbnail failed: %s",
                    result.stderr.decode("utf-8", "replace"),
                )
                return None
            img = QImage(out_path)
            if img.isNull():
                return None
            self._put_cache(src, ms, img)
            return img
        except Exception:
            _log.exception("thumbnail extraction error")
            return None
        finally:
            if out_path:
                try:
                    Path(out_path).unlink()
                except OSError:
                    pass

    def _put_cache(self, src: str, ms: int, img: QImage) -> None:
        key = (src, int(ms))
        self._cache[key] = img
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)   # LRU evict
