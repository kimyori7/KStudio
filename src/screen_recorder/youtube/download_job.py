"""YouTubeDownloadJob — yt-dlp 다운로드를 QThread 에서 실행 + 진행/완료/실패 시그널.

agent/models/downloader.py 의 QObject+QThread+Signal 패턴을 따른다. progress_hook 은
worker 스레드에서 호출되므로 UI 갱신은 반드시 시그널 emit(큐 연결)으로만 한다.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, Signal

from .request import DownloadRequest
from . import ytdlp_runner

_log = logging.getLogger(__name__)

# (req, ffmpeg_dir, progress_hook, cancel_check) -> 최종 파일 경로
Runner = Callable[
    [DownloadRequest, Path, Callable[[dict], None], Optional[Callable[[], bool]]],
    str,
]


class YouTubeDownloadJob(QObject):
    # int 오버플로 회피 위해 object (downloader.py 와 동일 이유 — 큰 파일 bytes).
    progress = Signal(object, object)   # (downloaded_bytes, total_bytes)
    speed = Signal(object)              # bytes/sec (None 가능)
    title_resolved = Signal(str)
    finished = Signal(str)              # 최종 파일 경로
    error = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        req: DownloadRequest,
        ffmpeg_dir: Path,
        runner: Optional[Runner] = None,
    ) -> None:
        super().__init__()
        self._req = req
        self._ffmpeg_dir = ffmpeg_dir
        self._runner: Runner = runner or ytdlp_runner.run_download
        self._cancel = False
        self._thread: Optional[QThread] = None
        self._worker: Optional[_Worker] = None

    @property
    def request(self) -> DownloadRequest:
        return self._req

    def start(self) -> None:
        self._thread = QThread()
        worker = _Worker(self._req, self._ffmpeg_dir, self._runner, lambda: self._cancel)
        worker.moveToThread(self._thread)
        worker.progress.connect(self.progress)
        worker.speed.connect(self.speed)
        worker.title_resolved.connect(self.title_resolved)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.done.connect(self._thread.quit)
        worker.failed.connect(self._thread.quit)
        worker.cancelled.connect(self._thread.quit)
        self._thread.started.connect(worker.run)
        self._worker = worker
        self._thread.start()

    def cancel(self) -> None:
        self._cancel = True

    def _on_done(self, path: str) -> None:
        self.finished.emit(path)

    def _on_failed(self, msg: str) -> None:
        self.error.emit(msg)

    def _on_cancelled(self) -> None:
        self.cancelled.emit()


class _Worker(QObject):
    progress = Signal(object, object)
    speed = Signal(object)
    title_resolved = Signal(str)
    done = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, req, ffmpeg_dir, runner, cancel_check) -> None:
        super().__init__()
        self._req = req
        self._ffmpeg_dir = ffmpeg_dir
        self._runner = runner
        self._cancel_check = cancel_check

    def run(self) -> None:
        def hook(d: dict) -> None:
            if d.get("status") == "downloading":
                got = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                self.progress.emit(got, total)
                self.speed.emit(d.get("speed"))
                info = d.get("info_dict") or {}
                title = info.get("title")
                if title:
                    self.title_resolved.emit(str(title))

        try:
            path = self._runner(self._req, self._ffmpeg_dir, hook, self._cancel_check)
            self.done.emit(path)
        except ytdlp_runner.CancelledError:
            self._cleanup_partials()
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001
            _log.exception("YouTubeDownloadJob 실패")
            self._cleanup_partials()
            self.failed.emit(str(exc))

    def _cleanup_partials(self) -> None:
        try:
            for pattern in ("*.part", "*.ytdl"):
                for f in self._req.out_dir.glob(pattern):
                    try:
                        f.unlink()
                    except OSError:
                        pass
        except OSError:
            pass
