"""ModelDownloadJob — HuggingFace 모델 비동기 다운로드 + 진행률 polling.

snapshot_download 가 blocking + tqdm 진행률 표시 — Qt Signal 못 받음.
따라서 (1) snapshot_download 는 별도 QThread 에서 실행, (2) 진행률은 cache dir
크기 변화를 polling 으로 측정 → emit. faster-whisper 다운로드 watcher 와 동일 패턴.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal


_log = logging.getLogger(__name__)


def _cache_dir_for_repo(repo_id: str) -> Optional[Path]:
    """HF 캐시 안 해당 repo 의 디렉토리. 없으면 None."""
    try:
        from huggingface_hub import constants
        # HF Hub 변환: "Qwen/Qwen2.5-Omni-7B" → "models--Qwen--Qwen2.5-Omni-7B"
        dir_name = "models--" + repo_id.replace("/", "--")
        return Path(constants.HF_HUB_CACHE) / dir_name
    except Exception:
        return None


def _dir_size_bytes(d: Path) -> int:
    """디렉토리 안 모든 파일 크기 합 (재귀). 디렉토리 없으면 0."""
    if not d.exists():
        return 0
    total = 0
    try:
        for f in d.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    return total


class ModelDownloadJob(QObject):
    """HF snapshot_download + 진행률 polling.

    수명주기:
    - start() — QThread 생성 + snapshot_download 시작. polling QTimer 도 시작.
    - finished(repo_id) — 다운로드 정상 완료.
    - error(msg) — 다운로드 실패.
    - download_progress(received, total) — polling 마다 emit.
    """

    download_progress = Signal(int, int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        repo_id: str,
        estimated_size_bytes: int = 0,
        poll_interval_ms: int = 500,
    ) -> None:
        super().__init__()
        self._repo_id = repo_id
        self._estimated_size = estimated_size_bytes
        self._poll_interval = poll_interval_ms
        self._thread: Optional[QThread] = None
        self._timer: Optional[QTimer] = None
        self._worker: Optional[_DownloadWorker] = None

    def start(self) -> None:
        """다운로드 + polling 시작. 한 번만 호출."""
        self._thread = QThread()
        worker = _DownloadWorker(self._repo_id)
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        worker.finished_ok.connect(self._on_worker_done)
        worker.failed.connect(self._on_worker_failed)
        worker.finished_ok.connect(self._thread.quit)
        worker.failed.connect(self._thread.quit)
        self._worker = worker
        self._thread.start()

        self._timer = QTimer(self)
        self._timer.setInterval(self._poll_interval)
        self._timer.timeout.connect(self._poll_progress)
        self._timer.start()

    def _poll_progress(self) -> None:
        cache_dir = _cache_dir_for_repo(self._repo_id)
        if cache_dir is None:
            return
        received = _dir_size_bytes(cache_dir)
        self.download_progress.emit(received, self._estimated_size)

    def _on_worker_done(self, repo_id: str) -> None:
        if self._timer:
            self._timer.stop()
        # 마지막 progress 한 번 더 — 100% 도달 표시.
        self._poll_progress()
        self.finished.emit(repo_id)

    def _on_worker_failed(self, msg: str) -> None:
        if self._timer:
            self._timer.stop()
        self.error.emit(msg)


class _DownloadWorker(QObject):
    """QThread 안에서 snapshot_download 호출."""

    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, repo_id: str) -> None:
        super().__init__()
        self._repo_id = repo_id

    def run(self) -> None:
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id=self._repo_id)
            self.finished_ok.emit(self._repo_id)
        except Exception as exc:
            _log.exception("ModelDownloadJob: snapshot_download 실패")
            self.failed.emit(str(exc))
