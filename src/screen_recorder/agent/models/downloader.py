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

    # `object` 타입 — Signal(int, int) 는 C qint32 (~2.1GB) 한계로 5GB 모델 다운로드
    # 중 OverflowError + 슬롯 호출 자체 실패 → bar 가 "멈춰있음" 으로 보임 (사용자 보고
    # 2026-05-26). qint64 로만 바꿔도 수신 슬롯 (update_progress) 가 Python int 라
    # Qt 가 (int,int) 로 등록 → signature 미스매치. `object` 면 PyObject* 로 통과 →
    # Qt 타입 마샬링 자체 없음.
    download_progress = Signal(object, object)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        repo_id: str,
        estimated_size_bytes: int = 0,
        poll_interval_ms: int = 500,
        *,
        allow_patterns: Optional[list[str]] = None,
        ignore_patterns: Optional[list[str]] = None,
    ) -> None:
        super().__init__()
        self._repo_id = repo_id
        self._estimated_size = estimated_size_bytes
        self._poll_interval = poll_interval_ms
        # HF snapshot_download 패턴 필터 (2026-05-27): 기본 호출은 repo 의 모든 파일을
        # 받는데 SDXL 같은 diffusers repo 는 fp32 .bin + fp16 .safetensors + native
        # 등 변형이 다 있어 추정의 4배까지 받게 됨. variant 만 골라받게 패턴 명시.
        self._allow_patterns = allow_patterns
        self._ignore_patterns = ignore_patterns
        self._thread: Optional[QThread] = None
        self._timer: Optional[QTimer] = None
        self._worker: Optional[_DownloadWorker] = None

    def start(self) -> None:
        """다운로드 + polling 시작. 한 번만 호출."""
        self._thread = QThread()
        worker = _DownloadWorker(
            self._repo_id,
            allow_patterns=self._allow_patterns,
            ignore_patterns=self._ignore_patterns,
        )
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        worker.finished_ok.connect(self._on_worker_done)
        worker.failed.connect(self._on_worker_failed)
        worker.finished_ok.connect(self._thread.quit)
        worker.failed.connect(self._thread.quit)
        self._worker = worker
        self._thread.start()

        self._poll_count = 0
        # 첫 polling 즉시 — 사용자가 "안 움직임" 으로 오해할 0초 갭 단축. 캐시에 이미
        # 일부 파일이 있으면 (resume) 첫 emit 만으로도 실제 진행률 표시.
        self._poll_progress()
        self._timer = QTimer(self)
        self._timer.setInterval(self._poll_interval)
        self._timer.timeout.connect(self._poll_progress)
        self._timer.start()
        _log.info(
            "ModelDownloadJob started: repo=%s interval=%dms estimate=%dMB",
            self._repo_id, self._poll_interval,
            self._estimated_size // (1024 * 1024) if self._estimated_size else 0,
        )

    def _poll_progress(self) -> None:
        cache_dir = _cache_dir_for_repo(self._repo_id)
        if cache_dir is None:
            return
        received = _dir_size_bytes(cache_dir)
        self._poll_count = getattr(self, "_poll_count", 0) + 1
        # 첫 5회 + 이후 매 20회 만 로깅 — log 폭주 방지 + 사용자 보고 시 디버그용.
        if self._poll_count <= 5 or self._poll_count % 20 == 0:
            mb = received // (1024 * 1024)
            _log.info(
                "ModelDownloadJob poll #%d: cache=%s received=%dMB",
                self._poll_count, cache_dir.name, mb,
            )
        self.download_progress.emit(received, self._estimated_size)

    def _on_worker_done(self, repo_id: str) -> None:
        if self._timer:
            self._timer.stop()
        # 마지막 progress emit — bar 가 시각적으로 100% 에 도달하도록 total=received 강제.
        # estimated_size 는 메타데이터의 사람 추정값이라 실제 cache 크기와 다름:
        # HF Hub 가 일부 파일을 dedup 하거나 사용자가 일부 파일만 받는 경우 추정보다 작음
        # → bar 가 60% 같은 어중간한 값에서 끝나 사용자가 "멈춰있음" 으로 오해. 완료 시점엔
        # cache 측정값을 total 로도 사용해 정확히 100% 표시.
        cache_dir = _cache_dir_for_repo(repo_id)
        received = _dir_size_bytes(cache_dir) if cache_dir is not None else 0
        # received=0 회피 — 빈 dir 면 update_progress 가 "전체 크기 미정" 분기로 빠짐.
        total_for_display = received if received > 0 else 1
        self.download_progress.emit(received, total_for_display)
        _log.info("ModelDownloadJob finished: repo=%s polls=%d received=%dMB",
                  repo_id, getattr(self, "_poll_count", 0), received // (1024 * 1024))
        self.finished.emit(repo_id)

    def _on_worker_failed(self, msg: str) -> None:
        if self._timer:
            self._timer.stop()
        _log.warning("ModelDownloadJob failed: %s", msg)
        self.error.emit(msg)


class _DownloadWorker(QObject):
    """QThread 안에서 snapshot_download 호출."""

    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        repo_id: str,
        *,
        allow_patterns: Optional[list[str]] = None,
        ignore_patterns: Optional[list[str]] = None,
    ) -> None:
        super().__init__()
        self._repo_id = repo_id
        self._allow_patterns = allow_patterns
        self._ignore_patterns = ignore_patterns

    def run(self) -> None:
        try:
            from huggingface_hub import snapshot_download
            kwargs = {"repo_id": self._repo_id}
            if self._allow_patterns:
                kwargs["allow_patterns"] = self._allow_patterns
            if self._ignore_patterns:
                kwargs["ignore_patterns"] = self._ignore_patterns
            snapshot_download(**kwargs)
            self.finished_ok.emit(self._repo_id)
        except Exception as exc:
            _log.exception("ModelDownloadJob: snapshot_download 실패")
            self.failed.emit(str(exc))
