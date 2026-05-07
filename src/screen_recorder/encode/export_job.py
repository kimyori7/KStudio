"""export_job — Sidecar export 백그라운드 작업.

src/screen_recorder/encode/trim.py 의 TrimJob 패턴을 그대로 따른다 — QObject +
daemon thread + stderr 파싱으로 progress 보고, cancel 지원, stderr.log 보존.
차이: argv 와 png_paths 를 외부에서 받는다 (export_pipeline.build_export_args 호출
결과). finished 시점에 임시 PNG 들 정리.
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
_TIME_RE = re.compile(r"time=(\d{2}):(\d{2}):(\d{2})\.(\d{1,3})")


def _parse_progress_ms(line: str) -> Optional[int]:
    m = _TIME_RE.search(line)
    if not m:
        return None
    h, mn, s, frac = m.groups()
    frac_ms = int(frac.ljust(3, "0")[:3])
    return ((int(h) * 60 + int(mn)) * 60 + int(s)) * 1000 + frac_ms


class ExportJob(QObject):
    progress = Signal(int)        # 0..100
    finished = Signal(object)     # dst Path
    error = Signal(str)

    def __init__(self, *,
                 ffmpeg_path: Path,
                 argv: list[str],
                 png_paths: list[Path],
                 dst_path: Path,
                 total_duration_ms: int,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._ffmpeg = Path(ffmpeg_path)
        self._argv = list(argv)
        self._png_paths = [Path(p) for p in png_paths]
        self._dst = Path(dst_path)
        self._total_ms = max(1, int(total_duration_ms))
        self._thread: Optional[threading.Thread] = None
        self._cancelled = False
        self._proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="ExportJob")
        self._thread.start()

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc is not None:
            try:
                self._proc.terminate()
            except OSError:
                pass

    def _run(self) -> None:
        log = logging.getLogger(__name__)
        stderr_log_path = self._dst.with_suffix(self._dst.suffix + ".ffmpeg.log")
        try:
            stderr_log = open(stderr_log_path, "wb")
        except OSError:
            stderr_log = None

        last_err = ""
        try:
            self._proc = subprocess.Popen(
                self._argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=_NO_WINDOW,
            )
        except OSError as e:
            self._cleanup_pngs()
            if stderr_log is not None:
                stderr_log.close()
            self.error.emit(f"ffmpeg 실행 실패: {e}")
            return

        try:
            assert self._proc.stderr is not None
            for raw in self._proc.stderr:
                if self._cancelled:
                    break
                if stderr_log is not None:
                    stderr_log.write(raw)
                line = raw.decode("utf-8", errors="replace").rstrip()
                if "error" in line.lower() or "invalid" in line.lower():
                    last_err = line
                ms = _parse_progress_ms(line)
                if ms is not None:
                    pct = max(0, min(100, int(ms * 100 / self._total_ms)))
                    self.progress.emit(pct)
        except Exception as e:
            log.exception("export stderr read crashed")
            last_err = f"stderr 처리 중 예외: {e}"

        rc = self._proc.wait()
        if stderr_log is not None:
            stderr_log.close()

        if self._cancelled:
            self._cleanup_partial(stderr_log_path)
            self._cleanup_pngs()
            self.error.emit("사용자가 취소함")
            return
        if rc != 0:
            self._cleanup_partial(stderr_log_path, keep_log=True)
            self._cleanup_pngs()
            self.error.emit(last_err or f"ffmpeg failed (exit {rc})")
            return

        # 성공 — log 정리
        try:
            stderr_log_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._cleanup_pngs()
        self.finished.emit(self._dst)

    def _cleanup_partial(self, log_path: Path, *, keep_log: bool = False) -> None:
        try:
            self._dst.unlink(missing_ok=True)
        except OSError:
            pass
        if not keep_log:
            try:
                log_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _cleanup_pngs(self) -> None:
        for p in self._png_paths:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
