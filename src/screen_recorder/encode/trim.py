"""ffmpeg 트림 잡 — 영상/GIF 의 in~out 구간을 새 파일로 저장.

기존 video_encoder.py 의 subprocess 패턴(creationflags / stderr 로그) 을 그대로
따른다. 차이: 입력 파이프 없이 파일 → 파일이라 stdin 미사용.
"""
from __future__ import annotations
import logging
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_GIF_EXTS = {".gif"}

# ffmpeg progress 라인 파서 — "time=HH:MM:SS.MS" 추출.
_TIME_RE = re.compile(r"time=(\d{2}):(\d{2}):(\d{2})\.(\d{1,3})")


def _ms_to_sec_str(ms: int) -> str:
    """1234 → "1.234" — ffmpeg -ss/-to 인자 형식."""
    return f"{ms / 1000.0:.3f}"


def build_video_args(*, ffmpeg: Path, src: Path, dst: Path,
                     in_ms: int, out_ms: int) -> list[str]:
    """MP4/MKV/WebM 트림 — libx264 CRF 18 + AAC 128k 재인코딩.

    -ss 를 -i 뒤에 둬 정확도 우선 (키프레임 끌림 없음).
    """
    return [
        str(ffmpeg), "-y", "-loglevel", "info",
        "-i", str(src),
        "-ss", _ms_to_sec_str(in_ms),
        "-to", _ms_to_sec_str(out_ms),
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(dst),
    ]


def build_gif_args(*, ffmpeg: Path, src: Path, dst: Path,
                   in_ms: int, out_ms: int,
                   palette_path: Path) -> tuple[list[str], list[str]]:
    """GIF 트림 — palettegen + paletteuse 2-pass.

    -ss/-to 를 -i 앞에 두어 input-seek 사용. GIF 에서는 input-seek 이 안정적
    (output-seek 은 단색이거나 변화가 거의 없는 GIF 의 palettegen 단계에서
    빈 결과를 만들어 palette 파일이 아예 생성되지 않는 경우 발생).
    """
    pass1 = [
        str(ffmpeg), "-y", "-loglevel", "error",
        "-ss", _ms_to_sec_str(in_ms),
        "-to", _ms_to_sec_str(out_ms),
        "-i", str(src),
        "-vf", "fps=15,palettegen=stats_mode=diff",
        str(palette_path),
    ]
    pass2 = [
        str(ffmpeg), "-y", "-loglevel", "info",
        "-ss", _ms_to_sec_str(in_ms),
        "-to", _ms_to_sec_str(out_ms),
        "-i", str(src),
        "-i", str(palette_path),
        "-lavfi", "fps=15 [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5",
        str(dst),
    ]
    return pass1, pass2


def parse_progress_ms(line: str) -> Optional[int]:
    """ffmpeg stderr 한 줄에서 'time=' 토큰을 ms 로. 없으면 None."""
    m = _TIME_RE.search(line)
    if not m:
        return None
    h, mn, s, frac = m.groups()
    frac_ms = int(frac.ljust(3, "0")[:3])
    return ((int(h) * 60 + int(mn)) * 60 + int(s)) * 1000 + frac_ms


class TrimJob(QObject):
    """daemon 스레드에서 ffmpeg 호출. 시그널은 메인 스레드로 자동 전달 (QObject)."""

    progress = Signal(int)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, *, ffmpeg_path: Path,
                 src: Path, dst: Path,
                 in_ms: int, out_ms: int,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._ffmpeg = Path(ffmpeg_path)
        self._src = Path(src)
        self._dst = Path(dst)
        self._in_ms = max(0, int(in_ms))
        self._out_ms = max(self._in_ms, int(out_ms))
        self._duration_ms = max(1, self._out_ms - self._in_ms)
        self._is_gif = self._src.suffix.lower() in _GIF_EXTS
        self._thread: Optional[threading.Thread] = None
        self._cancelled = False

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="TrimJob",
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancelled = True

    def _run(self) -> None:
        log = logging.getLogger(__name__)
        stderr_log_path = self._dst.with_suffix(self._dst.suffix + ".ffmpeg.log")
        try:
            stderr_log = open(stderr_log_path, "wb")
        except OSError:
            stderr_log = None

        try:
            if self._is_gif:
                ok, last_err = self._run_gif(stderr_log)
            else:
                ok, last_err = self._run_video(stderr_log)
        except Exception as e:
            log.exception("trim crashed")
            self._cleanup_partial()
            if stderr_log is not None:
                try:
                    stderr_log.close()
                except Exception:
                    pass
            self.error.emit(f"트림 실행 중 예외: {e}")
            return

        if stderr_log is not None:
            try:
                stderr_log.close()
            except Exception:
                pass

        if not ok:
            self._cleanup_partial()
            self.error.emit(last_err or "ffmpeg failed")
            return

        try:
            stderr_log_path.unlink(missing_ok=True)
        except OSError:
            pass
        self.finished.emit(self._dst)

    def _run_video(self, stderr_log) -> tuple[bool, Optional[str]]:
        argv = build_video_args(
            ffmpeg=self._ffmpeg, src=self._src, dst=self._dst,
            in_ms=self._in_ms, out_ms=self._out_ms,
        )
        return self._spawn_and_track(argv, stderr_log)

    def _run_gif(self, stderr_log) -> tuple[bool, Optional[str]]:
        palette = self._dst.with_suffix(".palette.png")
        pass1, pass2 = build_gif_args(
            ffmpeg=self._ffmpeg, src=self._src, dst=self._dst,
            in_ms=self._in_ms, out_ms=self._out_ms,
            palette_path=palette,
        )
        ok1, err1 = self._spawn_and_track(pass1, stderr_log, weight=0.3, base=0)
        if not ok1:
            try:
                palette.unlink(missing_ok=True)
            except OSError:
                pass
            return False, err1
        ok2, err2 = self._spawn_and_track(pass2, stderr_log, weight=0.7, base=30)
        try:
            palette.unlink(missing_ok=True)
        except OSError:
            pass
        return ok2, err2

    def _spawn_and_track(self, argv: list[str], stderr_log,
                         *, weight: float = 1.0, base: int = 0) -> tuple[bool, Optional[str]]:
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=_NO_WINDOW,
            )
        except OSError as e:
            return False, f"ffmpeg 실행 실패: {e}"

        last_err_line = ""
        assert proc.stderr is not None
        while True:
            line_b = proc.stderr.readline()
            if not line_b:
                break
            try:
                line = line_b.decode("utf-8", errors="replace").rstrip()
            except Exception:
                line = ""
            if stderr_log is not None:
                try:
                    stderr_log.write(line_b)
                except Exception:
                    pass
            ms = parse_progress_ms(line)
            if ms is not None:
                pct = base + int(weight * min(100, max(0, ms * 100 // self._duration_ms)))
                self.progress.emit(min(100, pct))
            elif line:
                last_err_line = line
            if self._cancelled:
                proc.terminate()
                return False, "사용자 취소"

        proc.wait(timeout=10)
        if proc.returncode != 0:
            return False, f"ffmpeg 실패 (exit={proc.returncode}): {last_err_line}"
        return True, None

    def _cleanup_partial(self) -> None:
        for p in (self._dst, self._dst.with_suffix(".palette.png")):
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
