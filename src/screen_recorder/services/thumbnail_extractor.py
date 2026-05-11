"""ThumbnailExtractor — segment 시작 프레임 1장을 ffmpeg 로 추출 + LRU 캐시.

- 동기 API (`extract_sync`) 와 캐시 조회 API (`get_or_none`).
- 비동기 호출은 ThumbnailService (thumbnail_worker.py) 에서 QThreadPool 로 감쌈.
- src 가 빈 문자열이거나 파일 없으면 None.
- ffmpeg 경로: PATH 우선, 없으면 `bin/ffmpeg.exe` 동봉본 (KStudio 의 export 와 동일 경로).
"""
from __future__ import annotations
import logging
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QImage

from ..core.ffmpeg_check import find_ffmpeg


_log = logging.getLogger(__name__)
_THUMB_W = 96
_THUMB_H = 54


class ThumbnailExtractor:
    """LRU 캐시 + ffmpeg 1프레임 추출.

    UI 스레드에서 캐시 조회만 하고 실제 추출은 호출자가 백그라운드 처리 (Service).
    """

    def __init__(self, cache_size: int = 100,
                 ffmpeg_path: Optional[Path] = None) -> None:
        self._cache: "OrderedDict[tuple[str, int], QImage]" = OrderedDict()
        self._cache_size = cache_size
        # find_ffmpeg() 가 PATH 또는 bin/ffmpeg.exe 동봉 경로 반환. 호출 인자가 있으면 우선.
        self._ffmpeg_path: Optional[Path] = ffmpeg_path or find_ffmpeg()

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
        if not src:
            _log.info("thumbnail: empty src skipped")
            return None
        if not Path(src).exists():
            _log.warning("thumbnail: src not found: %s", src)
            return None
        if self._ffmpeg_path is None:
            _log.error(
                "thumbnail: ffmpeg not found (PATH 미설치 + bin/ffmpeg.exe 동봉본 없음) — "
                "track lane previews will be empty"
            )
            return None
        out_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".png", delete=False
            ) as tmp:
                out_path = tmp.name
            cmd = [
                str(self._ffmpeg_path), "-y", "-loglevel", "error",
                "-ss", f"{ms / 1000.0:.3f}",
                "-i", src,
                "-frames:v", "1",
                "-vf", (
                    f"scale={_THUMB_W}:{_THUMB_H}:force_original_aspect_ratio=decrease,"
                    f"pad={_THUMB_W}:{_THUMB_H}:(ow-iw)/2:(oh-ih)/2:black"
                ),
                out_path,
            ]
            _log.info("thumbnail: extract src=%s ms=%d → %s", src, ms, out_path)
            # Windows: 콘솔 창 깜빡임 방지.
            kwargs = {"capture_output": True, "timeout": 10}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            try:
                result = subprocess.run(cmd, **kwargs)
            except FileNotFoundError:
                _log.error(
                    "thumbnail: ffmpeg path %s 가 무효 — track lane previews will be empty",
                    self._ffmpeg_path,
                )
                return None
            if result.returncode != 0:
                _log.warning(
                    "thumbnail: ffmpeg rc=%d stderr=%s",
                    result.returncode,
                    result.stderr.decode("utf-8", "replace"),
                )
                return None
            img = QImage(out_path)
            if img.isNull():
                _log.warning("thumbnail: QImage load failed for %s", out_path)
                return None
            _log.info("thumbnail: ok src=%s ms=%d size=%dx%d",
                      src, ms, img.width(), img.height())
            self._put_cache(src, ms, img)
            return img
        except Exception:
            _log.exception("thumbnail: extraction error")
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
