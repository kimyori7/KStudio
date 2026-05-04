"""ffmpeg 필름스트립 잡 — 영상 길이를 N등분해 균등 간격 썸네일 N장 추출.

TrimJob 과 같은 패턴(QObject + daemon thread + Qt 시그널). 결과 이미지는
임시 PNG 시퀀스로 한 번에 생성한 뒤 메모리로 읽어와 N장 QImage 리스트로 전달.
"""
from __future__ import annotations
import logging
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def build_args(*, ffmpeg: Path, src: Path, out_pattern: Path,
               count: int, duration_ms: int, thumb_width: int) -> list[str]:
    """ffmpeg 단일 호출로 균등 간격 N장 추출.

    `fps=N/duration` 필터 — 영상 길이(초) 동안 정확히 N개 프레임 출력.
    `scale=W:-1` 로 가로 W, 세로는 비율 유지.
    """
    duration_sec = max(0.001, duration_ms / 1000.0)
    fps = count / duration_sec
    return [
        str(ffmpeg), "-y", "-loglevel", "error",
        "-i", str(src),
        "-vf", f"fps={fps:.6f},scale={thumb_width}:-1",
        "-frames:v", str(count),
        str(out_pattern),
    ]


def _adaptive_count(duration_ms: int, default: int) -> int:
    """영상이 너무 짧으면 N 을 줄임 (`duration / 0.2초` 와 default 중 작은 쪽)."""
    if duration_ms <= 0:
        return default
    cap = max(2, duration_ms // 200)
    return max(2, min(default, cap))


class FilmstripJob(QObject):
    """영상에서 N장의 썸네일을 비동기로 추출."""

    finished = Signal(list)   # list[QImage]
    error = Signal(str)

    def __init__(self, *, ffmpeg_path: Path,
                 src: Path,
                 duration_ms: int,
                 count: int = 20,
                 thumb_width: int = 96,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._ffmpeg = Path(ffmpeg_path)
        self._src = Path(src)
        self._duration_ms = max(0, int(duration_ms))
        self._count = _adaptive_count(self._duration_ms, max(2, int(count)))
        self._thumb_width = max(16, int(thumb_width))
        self._thread: Optional[threading.Thread] = None
        self._cancelled = False

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="FilmstripJob",
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancelled = True

    def _run(self) -> None:
        log = logging.getLogger(__name__)
        try:
            with tempfile.TemporaryDirectory(prefix="kstudio_filmstrip_") as tmp:
                tmp_dir = Path(tmp)
                pattern = tmp_dir / "frame_%04d.png"
                argv = build_args(
                    ffmpeg=self._ffmpeg, src=self._src, out_pattern=pattern,
                    count=self._count, duration_ms=self._duration_ms,
                    thumb_width=self._thumb_width,
                )
                try:
                    proc = subprocess.run(
                        argv,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        creationflags=_NO_WINDOW,
                        timeout=30,
                    )
                except (OSError, subprocess.TimeoutExpired) as e:
                    self.error.emit(f"ffmpeg 실행 실패: {e}")
                    return

                if self._cancelled:
                    return

                if proc.returncode != 0:
                    err = proc.stderr.decode("utf-8", errors="replace")[-200:].strip()
                    self.error.emit(f"ffmpeg 실패: {err}")
                    return

                images: list[QImage] = []
                for p in sorted(tmp_dir.glob("frame_*.png")):
                    img = QImage(str(p))
                    if not img.isNull():
                        images.append(img.copy())   # 임시 디렉토리 사라져도 보존되도록 deep copy
                if not images:
                    self.error.emit("필름스트립 추출 결과 비어 있음")
                    return
                self.finished.emit(images)
        except Exception as e:
            log.exception("filmstrip crashed")
            self.error.emit(f"필름스트립 추출 중 예외: {e}")
